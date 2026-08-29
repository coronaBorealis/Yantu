from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ..common import utc_now
from ..database.repositories import ResearchRepository
from .research_service import ResearchService


SERVICE_NAME = "Yantu"
ACCOUNT_PREFIX = "zotero:"
SKIPPED_ITEM_TYPES = {"attachment", "note", "annotation"}


class ZoteroCredentialStore(Protocol):
    def get(self, source_id: str) -> str: ...
    def set(self, source_id: str, value: str) -> None: ...
    def delete(self, source_id: str) -> None: ...


class SystemZoteroCredentialStore:
    def get(self, source_id: str) -> str:
        try:
            import keyring

            return str(
                keyring.get_password(SERVICE_NAME, f"{ACCOUNT_PREFIX}{source_id}") or ""
            )
        except Exception as exc:
            raise ValueError(f"无法读取 Windows 凭据库：{exc}") from exc

    def set(self, source_id: str, value: str) -> None:
        try:
            import keyring

            keyring.set_password(SERVICE_NAME, f"{ACCOUNT_PREFIX}{source_id}", value)
        except Exception as exc:
            raise ValueError(f"无法写入 Windows 凭据库：{exc}") from exc

    def delete(self, source_id: str) -> None:
        try:
            import keyring

            try:
                keyring.delete_password(SERVICE_NAME, f"{ACCOUNT_PREFIX}{source_id}")
            except keyring.errors.PasswordDeleteError:
                pass
        except Exception as exc:
            raise ValueError(f"无法清除 Windows 凭据库：{exc}") from exc


class ZoteroService:
    """Read-only Zotero local/Web API adapter with versioned incremental sync."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        credential_store: ZoteroCredentialStore | None = None,
        environment: Mapping[str, str] | None = None,
        transport=urlopen,
        timeout: int = 15,
    ) -> None:
        self.research = ResearchService(db_path)
        self.repository = ResearchRepository(db_path)
        self.credentials = credential_store or SystemZoteroCredentialStore()
        self.environment = os.environ if environment is None else environment
        self.transport = transport
        self.timeout = timeout

    def list_connections(self) -> list[dict[str, Any]]:
        return [self._public_source(source) for source in self.repository.list_sources()]

    def save_connection(self, values: Mapping[str, Any]) -> dict[str, Any]:
        source_id = str(values.get("id") or "")
        previous = self.repository.get_source(source_id) if source_id else None
        if previous and previous.get("sync_cursor") and any(
            str(values.get(key, previous.get(key)) or "")
            != str(previous.get(key) or "")
            for key in ("access_mode", "library_type", "library_id", "base_url")
        ):
            raise ValueError("已同步来源不能直接更换文库身份，请新建 Zotero 来源")
        source = self.research.save_source(values)
        key = str(values.get("api_key") or "").strip()
        if key:
            if self._environment_key():
                raise ValueError("Zotero API Key 由环境变量管理，不能在软件内覆盖")
            if len(key) < 8 or any(char.isspace() for char in key):
                raise ValueError("Zotero API Key 格式无效")
            self.credentials.set(str(source["id"]), key)
        return self._public_source(source)

    def delete_key(self, source_id: str) -> dict[str, Any]:
        source = self._source(source_id)
        if self._environment_key():
            raise ValueError("环境变量中的 Zotero API Key 不能从软件内删除")
        self.credentials.delete(source_id)
        return self._public_source(source)

    def test_connection(self, source_id: str) -> dict[str, Any]:
        source = self._source(source_id)
        payload, headers = self._get_json(
            self._items_url(source, {"limit": 1, "format": "json"}), source
        )
        if not isinstance(payload, list):
            raise ValueError("Zotero 返回的数据格式无法识别")
        server_id = headers.get("Zotero-Server-ID")
        self._verify_server(source, server_id)
        if (server_id and not source.get("server_id")) or source.get("last_sync_error"):
            restored_status = (
                "ok" if source.get("last_synced_at") else "never"
            )
            self.repository.update_source_sync(
                source_id,
                cursor=source.get("sync_cursor"),
                server_id=server_id,
                status=restored_status,
                error="",
                synced_at=source.get("last_synced_at"),
                updated_at=utc_now(),
            )
        return {
            "ok": True,
            "source_id": source_id,
            "server_id": server_id or headers.get("Zotero-Server-ID"),
            "library_version": headers.get("Last-Modified-Version"),
            "sample_count": len(payload),
        }

    def sync(self, source_id: str) -> dict[str, Any]:
        source = self._source(source_id)
        run_id = str(uuid.uuid4())
        started = utc_now()
        cursor_before = str(source.get("sync_cursor") or "0")
        self.repository.create_sync_run(
            {
                "id": run_id,
                "source_id": source_id,
                "status": "running",
                "cursor_before": cursor_before,
                "cursor_after": None,
                "imported_count": 0,
                "deleted_count": 0,
                "error": "",
                "started_at": started,
                "ended_at": None,
            }
        )
        self.repository.update_source_sync(
            source_id,
            cursor=source.get("sync_cursor"),
            server_id=None,
            status="running",
            error="",
            synced_at=source.get("last_synced_at"),
            updated_at=started,
        )
        imported = 0
        deleted = 0
        cursor_after: str | None = None
        server_id: str | None = None
        try:
            raw_items: list[dict[str, Any]] = []
            versions: set[str] = set()
            start = 0
            while True:
                query = {
                    "includeTrashed": 1,
                    "limit": 100,
                    "start": start,
                    "format": "json",
                }
                # Zotero's local API does not expose the Web API's /deleted
                # endpoint. Fetching the complete local library lets us
                # reconcile removals without making that unsupported request.
                if source["access_mode"] == "web":
                    query["since"] = cursor_before
                payload, headers = self._get_json(
                    self._items_url(source, query),
                    source,
                )
                if not isinstance(payload, list):
                    raise ValueError("Zotero 条目响应必须是数组")
                current_server = headers.get("Zotero-Server-ID")
                self._verify_server(source, current_server)
                if current_server:
                    server_id = current_server
                if headers.get("Last-Modified-Version"):
                    versions.add(str(headers["Last-Modified-Version"]))
                raw_items.extend(item for item in payload if isinstance(item, dict))
                if len(payload) < 100:
                    break
                start += 100

            deleted_payload: Any = {"items": []}
            if source["access_mode"] == "web":
                deleted_payload, deleted_headers = self._get_json(
                    self._library_url(
                        source, f"deleted?{urlencode({'since': cursor_before})}"
                    ),
                    source,
                )
                if deleted_headers.get("Last-Modified-Version"):
                    versions.add(str(deleted_headers["Last-Modified-Version"]))
            if len(versions) > 1:
                raise ValueError("Zotero 文库在同步过程中发生变化，请重新同步")
            cursor_after = next(iter(versions), cursor_before)

            current_keys: set[str] = set()
            for raw in raw_items:
                data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
                item_type = str(data.get("itemType") or "")
                if item_type in SKIPPED_ITEM_TYPES:
                    continue
                key = str(raw.get("key") or data.get("key") or "")
                if not key:
                    continue
                if not data.get("deleted"):
                    current_keys.add(key)
                self.research.save_item(self._map_item(source, raw, data))
                imported += 1
            if source["access_mode"] == "local":
                existing_keys = {
                    str(item["external_key"])
                    for item in self.repository.list_items(source_id=source_id)
                }
                deleted_keys = sorted(existing_keys - current_keys)
            else:
                deleted_keys = (
                    [str(key) for key in deleted_payload.get("items", [])]
                    if isinstance(deleted_payload, dict)
                    else []
                )
            deleted = self.repository.soft_delete_external_items(
                source_id, deleted_keys, utc_now()
            )
            ended = utc_now()
            self.repository.update_source_sync(
                source_id,
                cursor=cursor_after,
                server_id=server_id,
                status="ok",
                error="",
                synced_at=ended,
                updated_at=ended,
            )
            self.repository.finish_sync_run(
                run_id,
                status="completed",
                cursor_after=cursor_after,
                imported_count=imported,
                deleted_count=deleted,
                error="",
                ended_at=ended,
            )
            return {
                "ok": True,
                "source_id": source_id,
                "imported_count": imported,
                "deleted_count": deleted,
                "cursor_before": cursor_before,
                "cursor_after": cursor_after,
            }
        except Exception as exc:
            ended = utc_now()
            message = str(exc)[:500]
            self.repository.update_source_sync(
                source_id,
                cursor=source.get("sync_cursor"),
                server_id=None,
                status="error",
                error=message,
                synced_at=source.get("last_synced_at"),
                updated_at=ended,
            )
            self.repository.finish_sync_run(
                run_id,
                status="failed",
                cursor_after=None,
                imported_count=imported,
                deleted_count=deleted,
                error=message,
                ended_at=ended,
            )
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"Zotero 同步失败：{message}") from exc

    def list_collections(self, source_id: str) -> list[dict[str, Any]]:
        """Return Zotero collections as a flat tree with stable display paths."""
        source = self._source(source_id)
        raw_collections = self._get_paginated(source, "collections", {})
        collections: dict[str, dict[str, Any]] = {}
        for raw in raw_collections:
            data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
            key = str(raw.get("key") or data.get("key") or "").strip()
            name = str(data.get("name") or "").strip()
            if not key or not name:
                continue
            collections[key] = {
                "key": key,
                "name": name,
                "parent_key": str(data.get("parentCollection") or "") or None,
            }

        def path_for(key: str) -> tuple[str, int]:
            names: list[str] = []
            seen: set[str] = set()
            current = collections.get(key)
            while current and current["key"] not in seen:
                seen.add(current["key"])
                names.append(current["name"])
                current = collections.get(str(current.get("parent_key") or ""))
            names.reverse()
            return " / ".join(names), max(0, len(names) - 1)

        result = []
        for key, item in collections.items():
            path, depth = path_for(key)
            result.append({**item, "path": path, "depth": depth})
        return sorted(result, key=lambda item: item["path"].casefold())

    def preview_project_import(
        self, source_id: str, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Read candidates from Zotero without writing Yantu's database."""
        source = self._source(source_id)
        mode = str(values.get("mode") or "collection").strip().lower()
        if mode not in {"collection", "search"}:
            raise ValueError("导入方式必须是 collection 或 search")
        collection_key: str | None = None
        query = ""
        suffixes: list[str] = []
        if mode == "collection":
            collection_key = str(values.get("collection_key") or "").strip()
            if not collection_key:
                raise ValueError("请选择 Zotero 文件夹")
            collections = self.list_collections(source_id)
            by_key = {item["key"]: item for item in collections}
            if collection_key not in by_key:
                raise ValueError("Zotero 文件夹不存在")
            keys = {collection_key}
            if bool(values.get("include_subcollections", True)):
                changed = True
                while changed:
                    changed = False
                    for item in collections:
                        if item.get("parent_key") in keys and item["key"] not in keys:
                            keys.add(item["key"])
                            changed = True
            suffixes = [f"collections/{quote(key, safe='')}/items/top" for key in keys]
        else:
            query = str(values.get("query") or "").strip()
            if not query:
                raise ValueError("请输入论文标题、作者或年份")
            if len(query) > 200:
                raise ValueError("检索词不能超过 200 个字符")
            suffixes = ["items/top"]

        raw_items: list[dict[str, Any]] = []
        for suffix in suffixes:
            params: dict[str, Any] = {"format": "json"}
            if query:
                params.update({"q": query, "qmode": "titleCreatorYear"})
            raw_items.extend(self._get_paginated(source, suffix, params, maximum=500))

        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in raw_items:
            data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
            item_type = str(data.get("itemType") or "")
            key = str(raw.get("key") or data.get("key") or "")
            if not key or key in seen or item_type in SKIPPED_ITEM_TYPES or data.get("deleted"):
                continue
            seen.add(key)
            mapped = self._map_item(source, raw, data)
            candidates.append(
                {
                    "external_key": key,
                    "item_type": mapped["item_type"],
                    "title": mapped["title"],
                    "creators": mapped["creators"],
                    "publication_title": mapped["publication_title"],
                    "published_at": mapped["published_at"],
                    "doi": mapped["doi"],
                    "zotero_uri": self.research.zotero_select_uri(source, key),
                    "selected": True,
                }
            )
        candidates.sort(key=lambda item: (str(item.get("published_at") or ""), item["title"]), reverse=True)
        return {
            "source_id": source_id,
            "mode": mode,
            "collection_key": collection_key,
            "query": query,
            "items": candidates,
            "count": len(candidates),
            "truncated": len(seen) >= 500,
        }

    def confirm_project_import(
        self, project_id: str, source_id: str, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        source = self._source(source_id)
        mode = str(values.get("mode") or "collection").strip().lower()
        if mode not in {"collection", "search"}:
            raise ValueError("导入方式必须是 collection 或 search")
        raw_keys = values.get("item_keys")
        if not isinstance(raw_keys, list):
            raise ValueError("item_keys 必须是数组")
        item_keys = list(dict.fromkeys(str(key or "").strip() for key in raw_keys if str(key or "").strip()))
        if not item_keys:
            raise ValueError("请至少选择一篇论文")
        if len(item_keys) > 500:
            raise ValueError("单次最多导入 500 篇论文")

        saved_ids: list[str] = []
        for start in range(0, len(item_keys), 50):
            chunk = item_keys[start : start + 50]
            raw_items = self._get_paginated(
                source,
                "items/top",
                {"format": "json", "itemKey": ",".join(chunk)},
                maximum=50,
            )
            for raw in raw_items:
                data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
                item_type = str(data.get("itemType") or "")
                if item_type in SKIPPED_ITEM_TYPES or data.get("deleted"):
                    continue
                mapped = self._map_item(source, raw, data)
                mapped["add_to_inbox"] = False
                saved = self.research.save_item(mapped)
                saved_ids.append(str(saved["id"]))
        linked = self.research.link_project_items(
            project_id,
            saved_ids,
            import_mode=mode,
            collection_key=str(values.get("collection_key") or "") or None,
            note="从 Zotero 文件夹导入" if mode == "collection" else "通过 Zotero 检索导入",
        )
        return {
            "project_id": project_id,
            "requested_count": len(item_keys),
            "resolved_count": len(set(saved_ids)),
            "imported_count": linked,
            "existing_count": len(set(saved_ids)) - linked,
            "items": self.research.list_project_items(project_id),
        }

    def _get_paginated(
        self,
        source: Mapping[str, Any],
        suffix: str,
        query: Mapping[str, Any],
        *,
        maximum: int | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        start = 0
        while maximum is None or len(results) < maximum:
            limit = min(100, maximum - len(results)) if maximum is not None else 100
            params = {**query, "limit": limit, "start": start}
            payload, headers = self._get_json(
                self._library_url(source, f"{suffix}?{urlencode(params)}"), source
            )
            if not isinstance(payload, list):
                raise ValueError("Zotero 返回的数据格式无法识别")
            self._verify_server(source, headers.get("Zotero-Server-ID"))
            results.extend(item for item in payload if isinstance(item, dict))
            if len(payload) < limit:
                break
            start += limit
        return results

    def _get_json(
        self, url: str, source: Mapping[str, Any]
    ) -> tuple[Any, Mapping[str, Any]]:
        request = Request(url, headers=self._headers(source))
        try:
            with self.transport(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8") or "null")
                headers = response.headers
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ValueError("Zotero 认证失败，或本机 API 尚未启用") from exc
            if exc.code == 412:
                raise ValueError("Zotero Server ID 已变化，请重新连接") from exc
            if exc.code == 429:
                raise ValueError("Zotero 请求过于频繁，请稍后重试") from exc
            raise ValueError(f"Zotero 连接失败（HTTP {exc.code}）") from exc
        except (URLError, TimeoutError, OSError) as exc:
            if source.get("access_mode") == "local":
                raise ValueError("无法连接本机 Zotero，请确认 Zotero 已启动并启用本地 API") from exc
            raise ValueError("无法连接 Zotero Web API") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Zotero 返回了无法识别的数据") from exc
        return payload, headers

    def _headers(self, source: Mapping[str, Any]) -> dict[str, str]:
        headers = {"Accept": "application/json", "Zotero-API-Version": "3"}
        if source["access_mode"] == "web":
            key = self._resolved_key(str(source["id"]))
            if not key:
                raise ValueError("请先保存 Zotero Web API Key")
            headers["Zotero-API-Key"] = key
        if source.get("access_mode") == "local" and source.get("server_id"):
            headers["Zotero-Server-ID"] = str(source["server_id"])
        return headers

    def _items_url(self, source: Mapping[str, Any], query: Mapping[str, Any]) -> str:
        return self._library_url(source, f"items/top?{urlencode(query)}")

    @staticmethod
    def _library_url(source: Mapping[str, Any], suffix: str) -> str:
        if source["library_type"] == "group":
            prefix = f"groups/{source['library_id']}"
        else:
            user_id = source["library_id"] if source["access_mode"] == "web" else "0"
            prefix = f"users/{user_id}"
        return f"{source['base_url']}/{prefix}/{suffix}"

    @staticmethod
    def _map_item(
        source: Mapping[str, Any], raw: Mapping[str, Any], data: Mapping[str, Any]
    ) -> dict[str, Any]:
        creators = []
        for creator in data.get("creators") or []:
            if not isinstance(creator, dict):
                continue
            creators.append(
                {
                    "creator_type": creator.get("creatorType", "author"),
                    "first_name": creator.get("firstName", ""),
                    "last_name": creator.get("lastName", ""),
                    "name": creator.get("name", ""),
                }
            )
        key = str(raw.get("key") or data.get("key"))
        return {
            "source_id": source["id"],
            "external_key": key,
            "item_type": data.get("itemType") or "document",
            "title": data.get("title") or f"未命名 Zotero 条目 {key}",
            "abstract": data.get("abstractNote") or "",
            "creators": creators,
            "publication_title": data.get("publicationTitle") or "",
            "published_at": data.get("date") or None,
            "doi": data.get("DOI") or "",
            "url": data.get("url") or "",
            "external_version": raw.get("version") or data.get("version"),
            "collected_at": data.get("dateAdded") or None,
            "last_synced_at": utc_now(),
            "deleted_at": utc_now() if data.get("deleted") else None,
            "add_to_inbox": not bool(data.get("deleted")),
            "metadata": {
                "tags": data.get("tags") or [],
                "collections": data.get("collections") or [],
                "relations": data.get("relations") or {},
                "date_modified": data.get("dateModified"),
            },
        }

    def _public_source(self, source: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(source)
        key = ""
        error = ""
        if source.get("access_mode") == "web":
            try:
                key = self._resolved_key(str(source["id"]))
            except ValueError as exc:
                error = str(exc)
        result.update(
            {
                "configured": source.get("access_mode") == "local" or bool(key),
                "credential_source": (
                    "not_required"
                    if source.get("access_mode") == "local"
                    else "environment"
                    if self._environment_key()
                    else "credential_manager"
                    if key
                    else "none"
                ),
                "masked_hint": f"••••{key[-4:]}" if key else "",
                "credential_error": error,
            }
        )
        return result

    def _source(self, source_id: str) -> dict[str, Any]:
        source = self.repository.get_source(source_id)
        if not source:
            raise ValueError("Zotero 来源不存在")
        if not source.get("enabled"):
            raise ValueError("Zotero 来源已停用")
        return source

    @staticmethod
    def _verify_server(source: Mapping[str, Any], current: str | None) -> None:
        expected = str(source.get("server_id") or "")
        if expected and current and expected != current:
            raise ValueError("检测到另一套 Zotero 数据库，请重新建立连接后再同步")

    def _environment_key(self) -> str:
        return str(self.environment.get("ZOTERO_API_KEY") or "").strip()

    def _resolved_key(self, source_id: str) -> str:
        return self._environment_key() or self.credentials.get(source_id)
