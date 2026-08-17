from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from .errors import ToolError
from .security import redact


_ALLOWED_COMMANDS = frozenset(
    {
        "health-check",
        "get-production-capabilities",
        "import-production-package",
        "run-production",
    }
)
_FORBIDDEN_COMMAND_FRAGMENTS = (
    "assemble-youtube-publish-package",
    "publish",
    "upload",
    "oauth",
    "analytics",
    "channel-learning",
)
_FORBIDDEN_STEP_FRAGMENTS = ("publish", "upload", "oauth", "receipt", "analytics", "learning")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_SAFE_STEP = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_WORKSHOP_START_LEASE_SECONDS = 300
_ACTIVE_WORKSHOP_TASK_STATES = frozenset({"running"})


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class WorkshopBridge:
    """Narrow Stage 5 process boundary for the installed workshop CLI.

    The bridge intentionally has no generic ``run`` method.  Publishing,
    OAuth, uploads, analytics and channel-learning commands cannot be reached
    through this API.  Every mutating import target must live below the
    caller-provided isolation root.
    """

    def __init__(
        self,
        executable: Path,
        isolation_root: Path,
        *,
        timeout_seconds: int = 120,
    ) -> None:
        self.executable = executable.resolve()
        self.isolation_root = isolation_root.resolve()
        self.timeout_seconds = max(1, int(timeout_seconds))
        if not self.executable.is_file():
            raise ToolError(
                "WORKSHOP_EXECUTABLE_MISSING",
                "新漫剧工坊程序不存在。",
                details={"executable": str(self.executable)},
            )
        self.isolation_root.mkdir(parents=True, exist_ok=True)

    def _validate_command(self, command: str, arguments: Iterable[str]) -> None:
        normalized = command.strip().lower()
        if normalized not in _ALLOWED_COMMANDS or any(
            fragment in normalized for fragment in _FORBIDDEN_COMMAND_FRAGMENTS
        ):
            raise ToolError(
                "WORKSHOP_COMMAND_FORBIDDEN",
                "阶段5工坊桥接拒绝了职责边界之外的命令。",
                details={"command": command},
            )

    def _run_json(
        self,
        command: str,
        arguments: list[str],
        *,
        accepted_exit_codes: frozenset[int] = frozenset({0}),
    ) -> dict[str, Any]:
        self._validate_command(command, arguments)
        result_root = self.isolation_root / ".workshop-bridge-results"
        result_root.mkdir(parents=True, exist_ok=True)
        result_path = result_root / f"{command}-{uuid.uuid4().hex}.json"
        argv = [str(self.executable), command, *arguments, "--result-file", str(result_path)]
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            completed = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                creationflags=creation_flags,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError(
                "WORKSHOP_COMMAND_TIMEOUT",
                "新漫剧工坊命令等待超时。",
                retryable=True,
                details={"command": command, "timeoutSeconds": self.timeout_seconds},
            ) from exc
        except OSError as exc:
            raise ToolError(
                "WORKSHOP_COMMAND_START_FAILED",
                "无法启动新漫剧工坊命令。",
                retryable=True,
                details={"command": command, "error": str(exc)},
            ) from exc

        payload: dict[str, Any] | None = None
        try:
            if result_path.is_file():
                candidate = json.loads(result_path.read_text(encoding="utf-8-sig"))
                if isinstance(candidate, dict):
                    payload = candidate
            if payload is None:
                lines = completed.stdout.strip().splitlines()
                if lines:
                    candidate = json.loads(lines[-1])
                    if isinstance(candidate, dict):
                        payload = candidate
        except (OSError, json.JSONDecodeError):
            payload = None
        finally:
            result_path.unlink(missing_ok=True)

        if completed.returncode not in accepted_exit_codes:
            safe_payload = redact(payload or {})
            message = str(safe_payload.get("error") or "").strip()
            if not message:
                message = str(redact(completed.stderr.strip() or completed.stdout.strip()))[:500]
            raise ToolError(
                "WORKSHOP_COMMAND_FAILED",
                message or f"新漫剧工坊命令失败（exit code {completed.returncode}）。",
                retryable=False,
                details={"command": command, "exitCode": completed.returncode},
            )
        if payload is None:
            raise ToolError(
                "WORKSHOP_RESULT_INVALID",
                "新漫剧工坊没有返回有效 JSON。",
                details={"command": command},
            )
        if payload.get("success") is not True:
            safe_payload = redact(payload)
            raise ToolError(
                "WORKSHOP_RESULT_FAILED",
                str(safe_payload.get("error") or "新漫剧工坊返回 success=false。"),
                details={"command": command},
            )
        return payload

    def health_check(self) -> dict[str, Any]:
        result = self._run_json("health-check", [])
        return {
            "success": True,
            "application": str(result.get("application") or ""),
            "version": str(result.get("version") or ""),
            "frontendEmbedded": bool(result.get("frontendEmbedded")),
            "ffmpegAvailable": bool(result.get("ffmpegAvailable")),
            "ffmpegPathSet": bool(str(result.get("ffmpegPath") or "").strip()),
            "ffprobePathSet": bool(str(result.get("ffprobePath") or "").strip()),
            "boundary": "read_only_no_external_services",
        }

    def capabilities(self) -> dict[str, Any]:
        result = self._run_json("get-production-capabilities", ["--no-probe"])
        return {
            "success": True,
            "defaultVoiceEngine": str(result.get("defaultVoiceEngine") or ""),
            "productionLanguage": str(result.get("productionLanguage") or ""),
            "voiceEngines": result.get("voiceEngines") if isinstance(result.get("voiceEngines"), list) else [],
            "supportedPackageVersions": (
                result.get("supportedPackageVersions")
                if isinstance(result.get("supportedPackageVersions"), list)
                else []
            ),
            "externalServiceProbeExecuted": False,
            "boundary": "read_only_no_external_services",
        }

    def import_package(
        self,
        package_root: Path,
        target_root: Path,
        *,
        expected_project_id: str,
    ) -> dict[str, Any]:
        package_root = package_root.resolve()
        target_root = target_root.resolve()
        if not package_root.is_dir() or not (package_root / "manifest.json").is_file():
            raise ToolError("PRODUCTION_PACKAGE_MISSING", "标准生产包目录或 manifest.json 不存在。")
        if any(part.lower().endswith(".ready") for part in package_root.parts):
            raise ToolError(
                "PUBLISHING_PACKAGE_FORBIDDEN",
                "制作中心不能导入发布中心 .ready 包。",
            )
        try:
            manifest = json.loads((package_root / "manifest.json").read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError("PRODUCTION_PACKAGE_MANIFEST_INVALID", "标准生产包 manifest.json 不可读。") from exc
        if not isinstance(manifest, dict) or str(manifest.get("schemaVersion") or "") != "2.1":
            raise ToolError(
                "PRODUCTION_PACKAGE_VERSION_UNSUPPORTED",
                "阶段5正式工坊移交只接受 schemaVersion=2.1。",
            )
        package_version = str(manifest.get("packageVersion") or "").strip()
        package_hash = str(manifest.get("packageHash") or "").strip().lower()
        manifest_project_id = str(manifest.get("projectId") or "").strip()
        if (
            manifest_project_id != expected_project_id
            or not package_version
            or re.fullmatch(r"[0-9a-f]{64}", package_hash) is None
        ):
            raise ToolError(
                "PRODUCTION_PACKAGE_IDENTITY_INVALID",
                "标准生产包缺少一致的项目 ID、包版本或 SHA-256 包哈希。",
            )
        if not _is_within(target_root, self.isolation_root) or target_root == self.isolation_root:
            raise ToolError(
                "WORKSHOP_TARGET_NOT_ISOLATED",
                "工坊导入目标必须位于本次隔离根目录的子目录中。",
                details={"target": str(target_root)},
            )
        target_root.mkdir(parents=True, exist_ok=True)
        result = self._run_json(
            "import-production-package",
            [str(package_root), "--target", str(target_root)],
        )
        project_id = str(result.get("projectId") or "")
        if project_id != expected_project_id:
            raise ToolError(
                "WORKSHOP_IMPORT_PROJECT_MISMATCH",
                "工坊导入结果的项目 ID 与标准生产包不一致。",
                details={"expected": expected_project_id, "actual": project_id},
            )
        project_path_text = str(result.get("projectPath") or "").strip()
        if not project_path_text:
            raise ToolError("WORKSHOP_IMPORT_RESULT_INVALID", "工坊导入结果缺少项目路径。")
        project_path = Path(project_path_text).resolve()
        if not _is_within(project_path, target_root):
            raise ToolError(
                "WORKSHOP_IMPORT_ESCAPED_TARGET",
                "工坊返回的项目路径超出了隔离导入目录。",
                details={"projectPath": str(project_path)},
            )
        if (
            str(result.get("packageVersion") or "") != package_version
            or str(result.get("packageHash") or "").lower() != package_hash
            or result.get("roundTripValidated") is not True
        ):
            raise ToolError(
                "WORKSHOP_IMPORT_ROUND_TRIP_FAILED",
                "工坊没有确认生产包版本、哈希和逐字段往返校验。",
            )
        project = self._load_official_project(project_path, expected_project_id)
        import_meta = project.get("importMeta")
        assert isinstance(import_meta, dict)
        if (
            str(import_meta.get("schemaVersion") or "") != "2.1"
            or str(import_meta.get("packageVersion") or "") != package_version
            or str(import_meta.get("packageHash") or "").lower() != package_hash
            or import_meta.get("contentLocked") is not True
            or import_meta.get("roundTripValidated") is not True
        ):
            raise ToolError(
                "WORKSHOP_IMPORT_IDENTITY_NOT_PERSISTED",
                "工坊项目没有持久化生产包 2.1 的版本、哈希和内容锁定身份。",
            )
        return {
            "success": True,
            "projectId": project_id,
            "projectName": str(result.get("projectName") or ""),
            "projectPath": str(project_path),
            "episodesImported": int(result.get("episodesImported") or 0),
            "charactersImported": int(result.get("charactersImported") or 0),
            "scriptLinesImported": int(result.get("scriptLinesImported") or 0),
            "duplicate": bool(result.get("duplicate")),
            "packageVersion": package_version,
            "packageHash": package_hash,
            "roundTripValidated": True,
            "warnings": [str(redact(item)) for item in result.get("warnings", [])],
            "boundary": "isolated_import_only",
            "publishingTriggered": False,
        }

    def _load_official_project(
        self,
        project_path: Path,
        expected_project_id: str | None,
    ) -> dict[str, Any]:
        try:
            project = json.loads(project_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError("WORKSHOP_PROJECT_INVALID", "工坊项目状态文件不可读。") from exc
        if not isinstance(project, dict):
            raise ToolError("WORKSHOP_PROJECT_INVALID", "工坊项目状态必须是 JSON 对象。")
        actual_project_id = str(project.get("id") or "")
        if expected_project_id and actual_project_id != expected_project_id:
            raise ToolError(
                "WORKSHOP_STATUS_PROJECT_MISMATCH",
                "工坊项目状态的项目 ID 不一致。",
                details={"expected": expected_project_id, "actual": actual_project_id},
            )
        import_meta = project.get("importMeta")
        if (
            not isinstance(import_meta, dict)
            or str(import_meta.get("source") or "") != "production_package"
            or str(import_meta.get("schemaVersion") or "") != "2.1"
            or import_meta.get("contentLocked") is not True
            or import_meta.get("roundTripValidated") is not True
        ):
            raise ToolError(
                "WORKSHOP_COMPATIBILITY_PROJECT_FORBIDDEN",
                "只有从正式生产包 2.1 导入并锁定内容的工坊项目才能进入阶段5生产。",
            )
        return project

    def _start_lease_path(self, project_path: Path) -> Path:
        lease_root = self.isolation_root / ".workshop-bridge-launches"
        lease_root.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(str(project_path.resolve()).casefold().encode("utf-8")).hexdigest()
        return lease_root / f"{key}.json"

    @staticmethod
    def _read_start_lease(lease_path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(lease_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _start_response_from_lease(lease: dict[str, Any]) -> dict[str, Any]:
        return {
            "success": True,
            "requestId": str(lease.get("requestId") or ""),
            "processId": int(lease.get("processId") or 0),
            "forwarded": False,
            "status": "start_pending",
            "selectedStepIds": [str(item) for item in lease.get("selectedStepIds", [])],
            "selectedEpisodeIds": [str(item) for item in lease.get("selectedEpisodeIds", [])],
            "skipCompleted": bool(lease.get("skipCompleted", True)),
            "joinedExisting": True,
            "startConfirmed": False,
            "boundary": "isolated_production_only",
            "publishingTriggered": False,
        }

    def _claim_start_lease(
        self,
        lease_path: Path,
        lease: dict[str, Any],
    ) -> dict[str, Any] | None:
        for _attempt in range(2):
            try:
                descriptor = os.open(lease_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                existing = self._read_start_lease(lease_path)
                created_at = float((existing or {}).get("createdAtEpoch") or 0)
                if existing and time.time() - created_at < _WORKSHOP_START_LEASE_SECONDS:
                    return existing
                lease_path.unlink(missing_ok=True)
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(lease, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
            return None
        existing = self._read_start_lease(lease_path)
        return existing or lease

    def start_production(
        self,
        project_path: Path,
        *,
        selected_step_ids: Iterable[str],
        selected_episode_ids: Iterable[str] = (),
        request_id: str | None = None,
        expected_project_id: str | None = None,
        skip_completed: bool = True,
        startup_timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        """Start/forward workshop production without waiting for media completion.

        Completion is observed with :meth:`production_status`, which only reads
        the isolated workshop project JSON.  The CLI is never asked to create a
        publisher package.
        """

        project_path = project_path.resolve()
        if not project_path.is_file() or not _is_within(project_path, self.isolation_root):
            raise ToolError(
                "WORKSHOP_PROJECT_NOT_ISOLATED",
                "只能启动位于本次隔离根目录中的工坊项目。",
                details={"projectPath": str(project_path)},
            )
        project = self._load_official_project(project_path, expected_project_id)
        steps = [str(item).strip() for item in selected_step_ids]
        episodes = [str(item).strip() for item in selected_episode_ids]
        if not steps or any(_SAFE_STEP.fullmatch(item) is None for item in steps):
            raise ToolError("WORKSHOP_STEPS_INVALID", "工坊生产步骤为空或包含无效标识。")
        if any(
            fragment in step.lower()
            for step in steps
            for fragment in _FORBIDDEN_STEP_FRAGMENTS
        ):
            raise ToolError(
                "WORKSHOP_COMMAND_FORBIDDEN",
                "阶段5生产步骤不得进入发布、上传、授权、回执、分析或学习写回。",
            )
        if any(_SAFE_IDENTIFIER.fullmatch(item) is None for item in episodes):
            raise ToolError("WORKSHOP_EPISODES_INVALID", "工坊分集标识无效。")
        request_id = request_id or f"stage5-{uuid.uuid4().hex}"
        if _SAFE_IDENTIFIER.fullmatch(request_id) is None:
            raise ToolError("WORKSHOP_REQUEST_ID_INVALID", "工坊请求 ID 无效。")

        task = project.get("autoProductionTask")
        if isinstance(task, dict) and str(task.get("status") or "").strip().lower() in _ACTIVE_WORKSHOP_TASK_STATES:
            active_request_id = str(task.get("externalRequestId") or request_id).strip()
            return {
                "success": True,
                "requestId": active_request_id,
                "processId": 0,
                "forwarded": True,
                "status": "already_running",
                "selectedStepIds": [str(item) for item in task.get("selectedStepIds", steps)],
                "selectedEpisodeIds": [str(item) for item in task.get("selectedEpisodeIds", episodes)],
                "skipCompleted": bool(skip_completed),
                "joinedExisting": True,
                "startConfirmed": True,
                "boundary": "isolated_production_only",
                "publishingTriggered": False,
            }

        arguments = [
            str(project_path),
            "--request-id",
            request_id,
            "--steps",
            ",".join(steps),
            "--auto-start",
        ]
        if episodes:
            arguments.extend(["--episodes", ",".join(episodes)])
        if not skip_completed:
            arguments.append("--no-skip-completed")
        self._validate_command("run-production", arguments)

        result_root = self.isolation_root / ".workshop-bridge-results"
        result_root.mkdir(parents=True, exist_ok=True)
        result_path = result_root / f"run-production-{uuid.uuid4().hex}.json"
        lease_path = self._start_lease_path(project_path)
        lease = {
            "requestId": request_id,
            "projectPath": str(project_path),
            "processId": 0,
            "resultPath": str(result_path),
            "createdAtEpoch": time.time(),
            "selectedStepIds": steps,
            "selectedEpisodeIds": episodes,
            "skipCompleted": bool(skip_completed),
        }
        existing_lease = self._claim_start_lease(lease_path, lease)
        if existing_lease is not None:
            return self._start_response_from_lease(existing_lease)
        argv = [
            str(self.executable),
            "run-production",
            *arguments,
            "--result-file",
            str(result_path),
        ]
        creation_flags = 0
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
        except OSError as exc:
            lease_path.unlink(missing_ok=True)
            result_path.unlink(missing_ok=True)
            raise ToolError(
                "WORKSHOP_COMMAND_START_FAILED",
                "无法启动新漫剧工坊生产命令。",
                retryable=True,
                details={"command": "run-production", "error": str(exc)},
            ) from exc

        lease["processId"] = process.pid
        lease_path.write_text(json.dumps(lease, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

        deadline = time.monotonic() + max(1, int(startup_timeout_seconds))
        payload: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            if result_path.is_file():
                try:
                    candidate = json.loads(result_path.read_text(encoding="utf-8-sig"))
                    if isinstance(candidate, dict):
                        payload = candidate
                        break
                except (OSError, json.JSONDecodeError):
                    pass
            return_code = process.poll()
            if return_code is not None:
                lease_path.unlink(missing_ok=True)
                result_path.unlink(missing_ok=True)
                raise ToolError(
                    "WORKSHOP_COMMAND_START_FAILED",
                    f"新漫剧工坊生产进程在登记任务前退出（exit code {return_code}）。",
                    retryable=True,
                    details={"command": "run-production", "exitCode": return_code},
                )
            time.sleep(0.1)
        if payload is None:
            return self._start_response_from_lease(lease)
        result_path.unlink(missing_ok=True)
        lease_path.unlink(missing_ok=True)
        if payload.get("success") is not True:
            safe_payload = redact(payload)
            raise ToolError(
                "WORKSHOP_START_REJECTED",
                str(safe_payload.get("error") or "工坊拒绝启动生产任务。"),
                retryable=False,
                details={"requestId": request_id},
            )
        return {
            "success": True,
            "requestId": request_id,
            "processId": int(payload.get("processId") or process.pid),
            "forwarded": bool(payload.get("forwarded")),
            "status": str(payload.get("status") or "accepted"),
            "selectedStepIds": steps,
            "selectedEpisodeIds": episodes,
            "skipCompleted": bool(skip_completed),
            "joinedExisting": False,
            "startConfirmed": True,
            "boundary": "isolated_production_only",
            "publishingTriggered": False,
        }

    def production_status(
        self,
        project_path: Path,
        *,
        expected_project_id: str,
        expected_request_id: str | None = None,
    ) -> dict[str, Any]:
        """Read the workshop task snapshot without changing any state."""

        project_path = project_path.resolve()
        if not project_path.is_file() or not _is_within(project_path, self.isolation_root):
            raise ToolError(
                "WORKSHOP_PROJECT_NOT_ISOLATED",
                "只能查询位于本次隔离根目录中的工坊项目。",
                details={"projectPath": str(project_path)},
            )
        project = self._load_official_project(project_path, expected_project_id)
        task = project.get("autoProductionTask")
        if not isinstance(task, dict):
            return {
                "success": True,
                "projectId": expected_project_id,
                "taskPresent": False,
                "status": "NOT_STARTED",
                "readOnly": True,
            }
        actual_request_id = str(task.get("externalRequestId") or "")
        if expected_request_id and actual_request_id != expected_request_id:
            raise ToolError(
                "WORKSHOP_STATUS_TASK_MISMATCH",
                "工坊运行副本不属于当前权威 Production Task 运行。",
                details={"expected": expected_request_id, "actual": actual_request_id},
            )
        episode_states = task.get("episodeStates")
        return {
            "success": True,
            "projectId": expected_project_id,
            "taskPresent": True,
            "taskId": str(task.get("id") or task.get("taskId") or ""),
            "externalRequestId": actual_request_id,
            "status": str(task.get("status") or "unknown"),
            "currentEpisodeId": str(task.get("currentEpisodeId") or ""),
            "currentStepId": str(task.get("currentStepId") or ""),
            "selectedStepIds": [str(item) for item in task.get("selectedStepIds", [])],
            "selectedEpisodeIds": [str(item) for item in task.get("selectedEpisodeIds", [])],
            "episodeStates": redact(episode_states) if isinstance(episode_states, dict) else {},
            "message": str(redact(task.get("message") or "")),
            "error": str(redact(task.get("error") or "")),
            "startedAt": task.get("startedAt"),
            "finishedAt": task.get("finishedAt"),
            "readOnly": True,
        }

    def production_artifacts(
        self,
        project_path: Path,
        *,
        expected_project_id: str,
        expected_request_id: str,
    ) -> dict[str, Any]:
        """Return real completed Workshop artifacts without mutating the project.

        Only paths below the isolated Workshop root are accepted.  This keeps
        the production center from accidentally harvesting an unrelated old
        project, desktop export, or user-selected file outside the task root.
        """

        project_path = project_path.resolve()
        if not project_path.is_file() or not _is_within(project_path, self.isolation_root):
            raise ToolError("WORKSHOP_PROJECT_NOT_ISOLATED", "只能回收隔离工坊项目的正式产物。")
        project = self._load_official_project(project_path, expected_project_id)
        task = project.get("autoProductionTask")
        if not isinstance(task, dict) or str(task.get("status") or "").strip().lower() != "completed":
            raise ToolError("WORKSHOP_PRODUCTION_NOT_COMPLETED", "工坊任务尚未完成，不能回收成片。")
        if str(task.get("externalRequestId") or "") != expected_request_id:
            raise ToolError("WORKSHOP_STATUS_TASK_MISMATCH", "完成的工坊任务不属于当前 Production Task。")

        def resolve_artifact(value: Any, field: str, *, required: bool = True) -> Path | None:
            text = str(value or "").strip()
            if not text:
                if required:
                    raise ToolError("WORKSHOP_ARTIFACT_MISSING", f"工坊完成结果缺少 {field}。")
                return None
            candidate = Path(text)
            if not candidate.is_absolute():
                candidate = project_path.parent / candidate
            candidate = candidate.resolve()
            if not _is_within(candidate, self.isolation_root):
                raise ToolError(
                    "WORKSHOP_ARTIFACT_OUTSIDE_ISOLATION",
                    f"工坊 {field} 超出当前隔离目录。",
                    details={"field": field},
                )
            if required and not candidate.is_file():
                raise ToolError("WORKSHOP_ARTIFACT_MISSING", f"工坊 {field} 文件不存在。")
            return candidate

        final_video = resolve_artifact(
            project.get("lastFinalVideoPath")
            or (project.get("publishing") or {}).get("finalVideoPath"),
            "finalVideoPath",
        )
        upload_package_text = str(
            project.get("lastUploadPackagePath")
            or (project.get("publishing") or {}).get("uploadPackagePath")
            or ""
        ).strip()
        upload_package = None
        if upload_package_text:
            upload_package = Path(upload_package_text)
            if not upload_package.is_absolute():
                upload_package = project_path.parent / upload_package
            upload_package = upload_package.resolve()
            if not upload_package.is_dir() or not _is_within(upload_package, self.isolation_root):
                raise ToolError("WORKSHOP_ARTIFACT_OUTSIDE_ISOLATION", "工坊成片资料包不在当前隔离目录中。")
        if upload_package is None:
            raise ToolError("WORKSHOP_UPLOAD_PACKAGE_MISSING", "工坊完成状态缺少成片资料包。")
        reports = sorted(upload_package.rglob("upload_package_report.json"))
        if len(reports) != 1:
            raise ToolError("WORKSHOP_UPLOAD_REPORT_INVALID", "工坊成片资料包必须且只能包含一份验收报告。")
        try:
            report = json.loads(reports[0].read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError("WORKSHOP_UPLOAD_REPORT_INVALID", "工坊成片验收报告不可读。") from exc
        if not isinstance(report, dict) or str(report.get("status") or "").lower() != "completed":
            raise ToolError("WORKSHOP_UPLOAD_REPORT_INVALID", "工坊成片验收报告没有完成。")
        subtitle = resolve_artifact(report.get("subtitlePath"), "subtitlePath")
        report_video = resolve_artifact(report.get("videoPath"), "report.videoPath")
        if report_video != final_video:
            raise ToolError("WORKSHOP_FINAL_VIDEO_MISMATCH", "工坊项目与验收报告指向了不同成片。")

        scene_values: list[dict[str, Any]] = []
        for item in project.get("scenes", []):
            if isinstance(item, dict):
                scene_values.append(item)
        twelve_grid = project.get("twelveGrid")
        if isinstance(twelve_grid, dict):
            scene_values.extend(item for item in twelve_grid.get("scenes", []) if isinstance(item, dict))
        by_episode = project.get("twelveGridByEpisodeId")
        if isinstance(by_episode, dict):
            for grid in by_episode.values():
                if isinstance(grid, dict):
                    scene_values.extend(item for item in grid.get("scenes", []) if isinstance(item, dict))
        images: list[dict[str, Any]] = []
        seen_scene_keys: set[tuple[str, str]] = set()
        for index, scene in enumerate(scene_values, 1):
            image_value = scene.get("splitImagePath") or scene.get("imagePath")
            if not str(image_value or "").strip():
                continue
            image = resolve_artifact(image_value, f"sceneImage[{index}]")
            scene_id = str(scene.get("id") or scene.get("sceneIndex") or index)
            key = (scene_id, str(image))
            if key in seen_scene_keys:
                continue
            seen_scene_keys.add(key)
            assert image is not None
            images.append(
                {
                    "sceneId": scene_id,
                    "path": str(image),
                    "sizeBytes": image.stat().st_size,
                    "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                }
            )
        if not images:
            raise ToolError("WORKSHOP_STORYBOARD_IMAGES_MISSING", "正式工坊结果没有任何分镜图片。")

        script_lines = []
        for item in project.get("scriptLines", []):
            if not isinstance(item, dict):
                continue
            script_lines.append(
                {
                    "lineId": str(item.get("id") or ""),
                    "durationSeconds": float(item.get("durationSec") or item.get("estimatedDurationSec") or 0),
                    "audioPath": str(item.get("audioPath") or ""),
                }
            )
        return {
            "success": True,
            "projectId": expected_project_id,
            "requestId": expected_request_id,
            "projectPath": str(project_path),
            "finalVideoPath": str(final_video),
            "subtitlePath": str(subtitle),
            "uploadPackagePath": str(upload_package),
            "uploadReportPath": str(reports[0].resolve()),
            "uploadReport": redact(report),
            "storyboardImages": images,
            "scriptLines": script_lines,
            "provenance": "workshop",
            "readOnly": True,
            "publishingTriggered": False,
        }


__all__ = ["WorkshopBridge"]
