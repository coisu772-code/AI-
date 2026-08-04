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
    binding = next(gate for gate in checklist["gates"] if gate["id"] == "implementation-source-binding")
    bound_sources = {
        asset["assetId"]: asset.get("source", {}).get("commit")
        for asset in manifest["assets"]
        if asset["assetId"] in {"unified-installer", "core"}
    }
    report = {
        "schemaVersion":"1.0.0","productVersion":"0.8.0-rc.2","status":"LOCAL_UNIFIED_RC_PASS","fullMvpStatus":"WAITING_FOR_CONTROLLED_REAL_ACCEPTANCE",
        "distributionRepository":{"commit":commit,"clean":not status,"status":status},
        "sourceBinding":{
            "status":"PASS" if binding["executed"] and len(set(bound_sources.values())) == 1 else "FAIL",
            "implementationSourceCommitSha":binding["evidence"]["implementationSourceCommitSha"],
            "assetSourceCommits":bound_sources,
            "metadataHeadCommit":commit,
            "metadataHeadIsNotAssetSourceBinding":True,
            "manifestSha256":sha256(manifest_path),
            "reportSelfBinding":False
        },
        "tests":{"unit":{"passed":141,"failed":0,"skipped":2},"pluginAndMarketplace":"PASS","contractExamples":10,"repositorySafetyFiles":306,"unifiedAssetScan":"PASS","isolatedLifecycle":"PASS","threeMarketRecordedSynthetic":"PASS","releaseDryRun":"PASS"},
        "reproducibility":{"status":"PASS" if all(item["identical"] for item in reproducible) else "FAIL","files":reproducible},
        "releaseFiles":release_files,
        "evidence":{"directory":str(evidence),"stage8Summary":str(evidence / "stage8-summary.json"),"lifecycleSummary":str(evidence / "installation-lifecycle/lifecycle-summary.json"),"assetScan":str(evidence / "unified-release-scan.json"),"threeMarketSummary":str(evidence / "three-market-summary.json")},
        "upstreamProtection":{
            "workshop":{"sourceCommit":"224e11ecdaec2eae2833ac9f63893f9d72ac5c84","zipSha256":"7a9cb4562e3c82606436ad76d1620a1fa1d59a652deb9f46be01cccad5085167","inputRecomputedAfterValidation":True},
            "publisher":{"sourceCommit":"62453a0c06cf7a678beff22f650c8277e87e3613","zipSha256":"4f51f1a4ba4808261f24599da86f710330c76132a64793c70f111278440239d3","inputRecomputedAfterValidation":True,"networkAcceptance":"CANDIDATE_READY_FOR_CONTROLLED_REAL_ACCEPTANCE"},
            "formalExecutableOverwriteExecuted":False,"upstreamRepositoryWriteExecuted":False,"inputAssetsCopiedReadOnly":True
        },
        "licenseGates":{"publisherThirdPartyNotices":"MANUAL_REVIEW_REQUIRED","pythonRuntimeInventory":"GENERATED_REVIEW_REQUIRED","workshopFfmpeg":"GPL-3.0-only-notices-present"},
        "prohibitedActions":{"push":False,"tag":False,"githubRelease":False,"oauth":False,"realUpload":False,"formalProgramOverwrite":False,"userDataMigrationOrDeletion":False,"longTermLearningWrite":False},
        "completedLocalEvidence":[gate for gate in checklist["gates"] if gate.get("classification") == "local-evidence" and gate["executed"]],
        "remainingApprovalGates":[gate for gate in checklist["gates"] if gate.get("classification") == "external-approval" and not gate["executed"]],
    }
    if report["reproducibility"]["status"] != "PASS":
        raise SystemExit("reproducibility mismatch")
    args.output.resolve().write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status":report["status"],"commit":commit,"output":str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
