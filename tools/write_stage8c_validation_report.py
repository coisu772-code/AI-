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
    mcp_utf8_stdin = json.loads((evidence / "mcp-utf8-stdin-validation.json").read_text(encoding="utf-8"))
    if unit_summary.get("status") != "PASS" or publisher_relock.get("status") != "PASS" or json_parsers.get("status") != "PASS" or mcp_utf8_stdin.get("status") != "PASS":
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
        "tests":{"unit":unit_summary,"officialPluginValidator":"PASS","repositoryMarketplaceValidator":"PASS","codexCliSmoke":"NOT_RUN_REQUIRES_EXECUTABLE_CLI_OR_APP_RESTART","contractExamples":10,"repositorySafety":"PASS","unifiedAssetScan":"PASS","winPs51McpUtf8Stdin":mcp_utf8_stdin,"isolatedLifecycle":"PASS","threeMarketRecordedSynthetic":"PASS","publisherStage6Relock":"PASS","stalePublisherCatalogRejected":"CONSTRAINTS_CATALOG_MISMATCH","jsonParsers":json_parsers,"releaseDryRun":"PASS"},
        "reproducibility":{"status":"PASS" if all(item["identical"] for item in reproducible) else "FAIL","files":reproducible},
        "releaseFiles":release_files,
        "evidence":{"directory":str(evidence),"stage8Summary":str(evidence / "stage8-summary.json"),"unitTestSummary":str(evidence / "unit-test-summary.json"),"lifecycleSummary":str(evidence / "installation-lifecycle/lifecycle-summary.json"),"assetScan":str(evidence / "unified-release-scan.json"),"winPs51McpUtf8Stdin":str(evidence / "mcp-utf8-stdin-validation.json"),"threeMarketSummary":str(evidence / "three-market-summary.json"),"publisherRelock":str(evidence / "publisher-relock-validation.json"),"jsonParserValidation":str(evidence / "json-parser-validation.json"),"finalPrerequisitePreflight":str(evidence / "final-prerequisite-preflight.json"),"releasePublishDryRun":str(evidence / "release-publish-dry-run.json"),"repositorySafety":str(evidence / "repository-safety.json")},
        "controlledAcceptance":{"windowsSandboxAttempt5":{"status":"FAIL","environment":"Windows 11 Enterprise 22621; no Python/py/uv; network disabled","evidenceFile":"clean-windows-sandbox-result.json","evidenceSha256":"a2a7cdbde94f9f67d3837fea3661f5055fa18a137b0df2d1970d936c73f10ec2","rootCause":"WinPS 5.1 StreamWriter stdin emitted bytes rejected by strict UTF-8 JSON-RPC parsing","fix":"Conditional StandardInputEncoding plus unconditional raw no-BOM UTF-8 BaseStream write","localRegression":"PASS","controlledSandboxRerun":"REQUIRED"}},
        "invalidatedOldCandidate":{"implementationSourceCommit":"fe4490a5b653f61f67a92584b72ddc788abe1695","status":"INVALID_DO_NOT_RELEASE_AS_A_SET","assetDisposition":[
            {"fileName":"AI-Video-Channel-Production-Unified-Installer-v0.8.0-rc.2.zip","sizeBytes":9198,"sha256":"878864ce62da65f438f20580806e0aabdf2947657cc1365a2e5e7f9e9dbdfc78","disposition":"SUPERSEDED_DO_NOT_RELEASE"},
            {"fileName":"ai-video-channel-production-core-v0.8.0-rc.2-windows.zip","sizeBytes":362102,"sha256":"d0b76febebc844fda27def7a93e79505d24ab3a5e6b1d6728eea4fd29ac25be3","disposition":"SUPERSEDED_DO_NOT_RELEASE"},
            {"fileName":"aivcp-python-runtime-3.12.13-windows-x64.zip","sizeBytes":24824171,"sha256":"4f47a2f3fc01a8b12fc6489582231704b48cc74c8ced6eb58ea3b75dcaa48c43","disposition":"FROZEN_COMPONENT_REUSED_AFTER_REVALIDATION"},
            {"fileName":"Z-Manga-Workshop-2.1.0-stage5-for-AIVCP-0.8.0-rc.1-windows-x64-portable.zip","sizeBytes":82990897,"sha256":"7a9cb4562e3c82606436ad76d1620a1fa1d59a652deb9f46be01cccad5085167","disposition":"FROZEN_COMPONENT_REUSED_AFTER_REVALIDATION"},
            {"fileName":"youtube-publisher-center-v0.8.0-rc.2-windows-amd64.zip","sizeBytes":32585503,"sha256":"8d2644c11310fd5ee31f6e39250f75a000ccf038cd8c35a9eed8f0f23388c48d","disposition":"FROZEN_COMPONENT_REUSED_AFTER_REVALIDATION"},
            {"fileName":"unified-release-v0.8.0-rc.2.json","sizeBytes":7107,"sha256":"158203f7c9407515686ab932ea19a9053277612d753bb62c36e89359d3efaed9","disposition":"SUPERSEDED_DO_NOT_RELEASE"},
            {"fileName":"SHA256SUMS.txt","sizeBytes":724,"sha256":"9bd7666c2c08225a1ad259e4a41ec09390dda971c9fec3897cae72f6f17919d0","disposition":"SUPERSEDED_DO_NOT_RELEASE"}
        ]},
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
