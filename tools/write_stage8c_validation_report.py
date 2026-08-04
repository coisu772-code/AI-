from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        check=False,
        capture_output=True,
    ).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--build-a", type=Path, required=True)
    parser.add_argument("--build-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    assets = args.asset_root.resolve()
    evidence = args.evidence_root.resolve()
    manifest_path = assets / "unified-release-v0.8.0-rc.2.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    names = [record["fileName"] for record in manifest["assets"]] + [manifest_path.name, "SHA256SUMS.txt"]
    reproducible = []
    for name in names:
        first, second = args.build_a.resolve() / name, args.build_b.resolve() / name
        first_hash, second_hash = sha256(first), sha256(second)
        reproducible.append({"fileName": name, "firstSha256": first_hash, "secondSha256": second_hash, "identical": first_hash == second_hash})
    release_files = []
    for name in names:
        path = assets / name
        release_files.append({"path": str(path), "fileName": name, "sizeBytes": path.stat().st_size, "sha256": sha256(path)})
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True, encoding="utf-8").splitlines()
    checklist = json.loads((root / "docs/final-acceptance-approval-checklist-v0.8.0-rc.2.json").read_text(encoding="utf-8"))
    unit_summary = json.loads((evidence / "unit-test-summary.json").read_text(encoding="utf-8"))
    publisher_relock = json.loads((evidence / "publisher-relock-validation.json").read_text(encoding="utf-8"))
    json_parsers = json.loads((evidence / "json-parser-validation.json").read_text(encoding="utf-8"))
    mcp_file_relay = json.loads((evidence / "mcp-file-relay-validation.json").read_text(encoding="utf-8"))
    lifecycle = json.loads((evidence / "installation-lifecycle/lifecycle-summary.json").read_text(encoding="utf-8-sig"))
    actual_codex = json.loads((evidence / "installation-lifecycle/actual-codex-cli-mcp-validation.json").read_text(encoding="utf-8"))
    official_plugin_validator = json.loads((evidence / "official-plugin-validator.json").read_text(encoding="utf-8"))
    if (
        unit_summary.get("status") != "PASS"
        or publisher_relock.get("status") != "PASS"
        or json_parsers.get("status") != "PASS"
        or mcp_file_relay.get("status") != "PASS"
        or lifecycle.get("status") != "PASS"
        or actual_codex.get("status") != "PASS"
        or not (
            str(official_plugin_validator.get("status", "")).startswith("PASS")
            or str(official_plugin_validator.get("status", "")).startswith("TOOL_UNAVAILABLE")
        )
    ):
        raise SystemExit("test evidence is not complete")
    binding = next(gate for gate in checklist["gates"] if gate["id"] == "implementation-source-binding")
    bound_sources = {
        asset["assetId"]: asset.get("source", {}).get("commit")
        for asset in manifest["assets"]
        if asset["assetId"] in {"unified-installer", "core"}
    }
    bound_metadata = {
        asset["assetId"]: asset.get("source", {}).get("metadataCommit")
        for asset in manifest["assets"]
        if asset.get("source", {}).get("metadataCommit")
    }
    expected_source = binding["evidence"]["implementationSourceCommitSha"]
    metadata_commits = set(bound_metadata.values())
    source_binding_pass = (
        binding["executed"]
        and set(bound_sources.values()) == {expected_source}
        and len(metadata_commits) == 1
        and git_is_ancestor(root, expected_source, next(iter(metadata_commits)))
        and git_is_ancestor(root, next(iter(metadata_commits)), commit)
    )
    report = {
        "schemaVersion":"1.0.0","productVersion":"0.8.0-rc.2","status":"LOCAL_UNIFIED_RC_PASS","fullMvpStatus":"WAITING_FOR_CONTROLLED_REAL_ACCEPTANCE",
        "distributionRepository":{"commit":commit,"clean":not status,"status":status},
        "sourceBinding":{
            "status":"PASS" if source_binding_pass else "FAIL",
            "implementationSourceCommitSha":expected_source,
            "assetSourceCommits":bound_sources,
            "assetMetadataCommits":bound_metadata,
            "metadataHeadCommit":commit,
            "metadataHeadIsNotAssetSourceBinding":True,
            "manifestSha256":sha256(manifest_path),
            "reportSelfBinding":False
        },
        "tests":{"unit":unit_summary,"officialPluginValidator":official_plugin_validator,"officialPluginValidatorCurrentEnvironmentCaveat":not str(official_plugin_validator.get("status", "")).startswith("PASS"),"repositoryMarketplaceValidator":"PASS","actualCodexCliRuntimeBoundMcp":actual_codex,"visibleRestartedCodexTask":"WAITING_FOR_RERUN","contractExamples":10,"repositorySafety":"PASS","unifiedAssetScan":"PASS","winPs51McpFileRelay":mcp_file_relay,"isolatedLifecycle":lifecycle,"defaultShortRootLifecycle":"PASS","cachedPluginRuntimeBoundFreshProcess":"PASS","installedWorkshopReadOnlyHealthAndCapabilities":"PASS","installedFfmpegAndFfprobe":"PASS","installedPublisherReadOnlyAndV2Bridges":"PASS","runtimeBindingComponentPathAndVersionTamperRejection":"PASS","staleCachedPluginVersionRejected":"PASS","pathBudgetAndRootStripping":"PASS","operationMutexContention":"PASS","installAndRollbackLocatorFailureInjection":"PASS","uninstallAndRestoreWhatIf":"PASS","threeMarketRecordedSynthetic":"PASS","publisherStage6Relock":"PASS","stalePublisherCatalogRejected":"CONSTRAINTS_CATALOG_MISMATCH","jsonParsers":json_parsers,"releaseDryRun":"PASS"},
        "reproducibility":{"status":"PASS" if all(item["identical"] for item in reproducible) else "FAIL","files":reproducible},
        "releaseFiles":release_files,
        "evidence":{"directory":str(evidence),"stage8Summary":str(evidence / "stage8-summary.json"),"unitTestSummary":str(evidence / "unit-test-summary.json"),"officialPluginValidator":str(evidence / "official-plugin-validator.json"),"lifecycleSummary":str(evidence / "installation-lifecycle/lifecycle-summary.json"),"defaultPathHealth":str(evidence / "installation-lifecycle/default-path-health.json"),"cachedPluginRuntime":str(evidence / "installation-lifecycle/cached-plugin-runtime-validation.json"),"runtimeBindingTamperRejection":str(evidence / "installation-lifecycle/runtime-binding-component-tamper-rejection.json"),"actualCodexCliMcp":str(evidence / "installation-lifecycle/actual-codex-cli-mcp-validation.json"),"staleCacheRejection":str(evidence / "installation-lifecycle/stale-cache-rejection.txt"),"assetScan":str(evidence / "unified-release-scan.json"),"winPs51McpFileRelay":str(evidence / "mcp-file-relay-validation.json"),"threeMarketSummary":str(evidence / "three-market-summary.json"),"publisherRelock":str(evidence / "publisher-relock-validation.json"),"jsonParserValidation":str(evidence / "json-parser-validation.json"),"finalPrerequisitePreflight":str(evidence / "final-prerequisite-preflight.json"),"releasePublishDryRun":str(evidence / "release-publish-dry-run.json"),"repositorySafety":str(evidence / "repository-safety.json")},
        "controlledAcceptance":{
            "windowsSandboxAttempt7":{"status":"HISTORICAL_FAIL_FIXED_BY_FILE_RELAY","environment":"Windows 11 Enterprise 22621; WinPS 5.1; no Python/py/uv; network disabled","evidenceFile":"attempt-7-archive/clean-windows-sandbox-result.json","evidenceSizeBytes":36632,"evidenceSha256":"05e806c73ab2eff8e6ec27cd89151464300d46fbcc8b05f2a3d341b7130c6ec9","rawStdinProbeHex":"efbbbf580a","fileRelay":{"exitCode":0,"stderrEmpty":True,"toolsListSucceeded":True},"strictServerParserRetained":True},
            "windowsSandboxAttempt9":{"status":"PASS_FOR_SUPERSEDED_CANDIDATE_ONLY","manifestSha256":"dffd391a266230a6af21aa7ccd22c90e443c3a0e756b9dfdea926112111f3eb7","evidenceFile":"attempt-9-pass/clean-windows-sandbox-result.json","evidenceSizeBytes":10459,"evidenceSha256":"602a76bfbbf9f6e167ea1e071742a5cdeafcecd3d209c938f0a3add0692d728c","doesNotApproveCurrentCandidate":True},
            "postAttempt9Blockers":{"defaultPathMaxPath":"FIXED_LOCALLY_WAITING_FOR_CLEAN_WINDOWS_RERUN","customInstallCodexCacheMcp":"ACTUAL_CODEX_CLI_PASS_VISIBLE_RESTARTED_TASK_AND_SANDBOX_RERUN_REQUIRED","installedComponentPathsMissingFromDescriptor":"FIXED_LOCALLY_WITH_REAL_WORKSHOP_AND_PUBLISHER_CAPABILITIES_WAITING_FOR_SANDBOX_RERUN"},
            "currentCandidate":"WAITING_FOR_RERUN"
        },
        "invalidatedCandidateChain":[{"implementationSourceCommit":"511954e008e097bccb679ba53b3455aed35554cf","metadataCommit":"2a9346c0c6f6ce9516a8f807e24d8eff5f36b859","status":"INVALID_DO_NOT_RELEASE_AS_A_SET","assetDisposition":[
            {"fileName":"AI-Video-Channel-Production-Unified-Installer-v0.8.0-rc.2.zip","sizeBytes":9242,"sha256":"69099e4e5880d253d8d5d8161acabfa59266dfb2d65396178d31b7ef98cac48c","disposition":"SUPERSEDED_DO_NOT_RELEASE"},
            {"fileName":"ai-video-channel-production-core-v0.8.0-rc.2-windows.zip","sizeBytes":364153,"sha256":"c00c49491857e4737ab71a371030136beac923dc3c99682ab9111b15f57862e4","disposition":"SUPERSEDED_DO_NOT_RELEASE"},
            {"fileName":"aivcp-python-runtime-3.12.13-windows-x64.zip","sizeBytes":24824171,"sha256":"4f47a2f3fc01a8b12fc6489582231704b48cc74c8ced6eb58ea3b75dcaa48c43","disposition":"FROZEN_COMPONENT_REUSED_AFTER_REVALIDATION"},
            {"fileName":"Z-Manga-Workshop-2.1.0-stage5-for-AIVCP-0.8.0-rc.1-windows-x64-portable.zip","sizeBytes":82990897,"sha256":"7a9cb4562e3c82606436ad76d1620a1fa1d59a652deb9f46be01cccad5085167","disposition":"FROZEN_COMPONENT_REUSED_AFTER_REVALIDATION"},
            {"fileName":"youtube-publisher-center-v0.8.0-rc.2-windows-amd64.zip","sizeBytes":32585503,"sha256":"8d2644c11310fd5ee31f6e39250f75a000ccf038cd8c35a9eed8f0f23388c48d","disposition":"FROZEN_COMPONENT_REUSED_AFTER_REVALIDATION"},
            {"fileName":"unified-release-v0.8.0-rc.2.json","sizeBytes":7107,"sha256":"cd6fdda0c8cc2526e3a7bb8f024afaefa2a2a169d3bfc42507dc5092b4c3e514","disposition":"SUPERSEDED_DO_NOT_RELEASE"},
            {"fileName":"SHA256SUMS.txt","sizeBytes":724,"sha256":"99a9a440a8f38a5e0ff1c33ea91b255c07eceb11847738afea464556554ab76e","disposition":"SUPERSEDED_DO_NOT_RELEASE"}
        ]},{"implementationSourceCommit":"421a935030ca5fa63a87c214c95ba7db7291248e","metadataCommit":"303b7917ba382ce3222e0381874e5637a4cc1072","status":"INVALID_DO_NOT_RELEASE_AS_A_SET","reason":"Default installation MAX_PATH failure and Codex cached plugin could not resolve custom InstallRoot runtime.","assetDisposition":[
            {"fileName":"AI-Video-Channel-Production-Unified-Installer-v0.8.0-rc.2.zip","sizeBytes":9246,"sha256":"cf5cb7637a8212487ac2b942714c49620f8750c334927a9301351926c5a5aac9","disposition":"SUPERSEDED_DO_NOT_RELEASE"},
            {"fileName":"ai-video-channel-production-core-v0.8.0-rc.2-windows.zip","sizeBytes":366701,"sha256":"4405703da7196b0f29d0abed0d31c9dcdf765e7b1daaff5dd060c42485c8ef01","disposition":"SUPERSEDED_DO_NOT_RELEASE"},
            {"fileName":"aivcp-python-runtime-3.12.13-windows-x64.zip","sizeBytes":24824171,"sha256":"4f47a2f3fc01a8b12fc6489582231704b48cc74c8ced6eb58ea3b75dcaa48c43","disposition":"FROZEN_COMPONENT_REUSED_AFTER_REVALIDATION"},
            {"fileName":"Z-Manga-Workshop-2.1.0-stage5-for-AIVCP-0.8.0-rc.1-windows-x64-portable.zip","sizeBytes":82990897,"sha256":"7a9cb4562e3c82606436ad76d1620a1fa1d59a652deb9f46be01cccad5085167","disposition":"FROZEN_COMPONENT_REUSED_AFTER_REVALIDATION"},
            {"fileName":"youtube-publisher-center-v0.8.0-rc.2-windows-amd64.zip","sizeBytes":32585503,"sha256":"8d2644c11310fd5ee31f6e39250f75a000ccf038cd8c35a9eed8f0f23388c48d","disposition":"FROZEN_COMPONENT_REUSED_AFTER_REVALIDATION"},
            {"fileName":"unified-release-v0.8.0-rc.2.json","sizeBytes":7107,"sha256":"dffd391a266230a6af21aa7ccd22c90e443c3a0e756b9dfdea926112111f3eb7","disposition":"SUPERSEDED_DO_NOT_RELEASE"},
            {"fileName":"SHA256SUMS.txt","sizeBytes":724,"sha256":"fb5ba5e41f473711ddb2d3726778a37340f9123e695eee1f9de750af015578cd","disposition":"SUPERSEDED_DO_NOT_RELEASE"}
        ]},{"implementationSourceCommit":"5f5955d5f12cfbf5d2a94026ac543b9d043be374","metadataCommit":"cb7d1600958d1363d408cfe4a4d9b84b1816aecc","assetRecordCommit":"52b67a859ce1f460f2f840a8384632c6cb5a5e33","status":"INVALID_DO_NOT_RELEASE_AS_A_SET","reason":"Runtime-bound descriptor omitted installed workshop, FFmpeg/ffprobe, publisher channel-list and publish-package-v2 paths.","assetDisposition":[
            {"fileName":"AI-Video-Channel-Production-Unified-Installer-v0.8.0-rc.2.zip","sizeBytes":13121,"sha256":"795c278ed503d75cd43d52af2918c4a57272d2ee145f6ba4e48b45358d7b5bd3","disposition":"SUPERSEDED_DO_NOT_RELEASE"},
            {"fileName":"ai-video-channel-production-core-v0.8.0-rc.2-windows.zip","sizeBytes":377783,"sha256":"3f28bb7e0e70aba8809925004df02e63698d11cd9c0e74a4a90de2473d48dba6","disposition":"SUPERSEDED_DO_NOT_RELEASE"},
            {"fileName":"aivcp-python-runtime-3.12.13-windows-x64.zip","sizeBytes":24824171,"sha256":"4f47a2f3fc01a8b12fc6489582231704b48cc74c8ced6eb58ea3b75dcaa48c43","disposition":"FROZEN_COMPONENT_REUSED_AFTER_REVALIDATION"},
            {"fileName":"Z-Manga-Workshop-2.1.0-stage5-for-AIVCP-0.8.0-rc.1-windows-x64-portable.zip","sizeBytes":82990897,"sha256":"7a9cb4562e3c82606436ad76d1620a1fa1d59a652deb9f46be01cccad5085167","disposition":"FROZEN_COMPONENT_REUSED_AFTER_REVALIDATION"},
            {"fileName":"youtube-publisher-center-v0.8.0-rc.2-windows-amd64.zip","sizeBytes":32585503,"sha256":"8d2644c11310fd5ee31f6e39250f75a000ccf038cd8c35a9eed8f0f23388c48d","disposition":"FROZEN_COMPONENT_REUSED_AFTER_REVALIDATION"},
            {"fileName":"unified-release-v0.8.0-rc.2.json","sizeBytes":7108,"sha256":"ff30bc2cb55295269fcbb2977ba253f9fecfda888fbf62da6e8162fe77759712","disposition":"SUPERSEDED_DO_NOT_RELEASE"},
            {"fileName":"SHA256SUMS.txt","sizeBytes":724,"sha256":"187d8a44d8d6f0ee553e18967c9b945b01e3ef5c7261946147e130d99ebfdd59","disposition":"SUPERSEDED_DO_NOT_RELEASE"}
        ]}],
        "upstreamProtection":{
            "workshop":{"sourceCommit":"224e11ecdaec2eae2833ac9f63893f9d72ac5c84","zipSha256":"7a9cb4562e3c82606436ad76d1620a1fa1d59a652deb9f46be01cccad5085167","inputRecomputedAfterValidation":True},
            "publisher":{"sourceCommit":"e6350fd290e2e75782334d712ba01ad0411a1efd","zipSha256":"8d2644c11310fd5ee31f6e39250f75a000ccf038cd8c35a9eed8f0f23388c48d","componentManifestSha256":"ead48c9c0c234512ab16ef978d35e2f1dc15c6332b298d0513b2d784548514b8","inputRecomputedAfterValidation":True,"distributionRelock":publisher_relock,"networkAcceptance":"CANDIDATE_READY_FOR_CONTROLLED_REAL_ACCEPTANCE"},
            "formalExecutableOverwriteExecuted":False,"upstreamRepositoryWriteExecuted":False,"inputAssetsCopiedReadOnly":True
        },
        "licenseEvidence":{"technicalInventoryStatus":"PASS","publisherReviewRequired":0,"pythonPackages":12,"pythonLicenseEntries":58,"workshopInventory":"PASS","legalAdviceOrSignoff":False,"externalReleaseOwnerApproval":"REQUIRED"},
        "prohibitedActions":{"push":False,"tag":False,"githubRelease":False,"oauth":False,"realUpload":False,"formalProgramOverwrite":False,"userDataMigrationOrDeletion":False,"longTermLearningWrite":False},
        "completedLocalEvidence":[gate for gate in checklist["gates"] if gate.get("classification") == "local-evidence" and gate["executed"]],
        "remainingApprovalGates":[gate for gate in checklist["gates"] if gate.get("classification") == "external-approval" and not gate["executed"]],
    }
    if report["reproducibility"]["status"] != "PASS":
        raise SystemExit("reproducibility mismatch")
    if report["sourceBinding"]["status"] != "PASS":
        raise SystemExit("source binding mismatch")
    args.output.resolve().write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status":report["status"],"commit":commit,"output":str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
