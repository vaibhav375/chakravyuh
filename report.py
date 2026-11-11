"""Post-call report: one JSON per call, shaped like a cyber-crime complaint, ready for a bank or the Suspect Registry.

The bot hears each side on its own stream, so the transcript is already speaker-labelled; no diarization needed.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from llm import groq

REPORTS = Path(__file__).parent / "reports"
IST = timezone(timedelta(hours=5, minutes=30))
SCAM_TYPES = ["digital_arrest", "courier_customs", "kyc_block", "electricity", "job_task", "stock_tips",
              "family_emergency", "lottery", "other", "not_a_scam"]


def suspects(identifiers):
    """Group identifiers the way complaint forms ask for them: each account with the IFSC given after it."""
    out, last_account = {"bank_accounts": [], "upi_ids": [], "mobiles": [], "links": []}, None
    for i in identifiers:
        if i["type"] == "account":
            last_account = {"account": i["value"], "ifsc": None}
            out["bank_accounts"].append(last_account)
        elif i["type"] == "ifsc":
            if last_account and not last_account["ifsc"]:
                last_account["ifsc"] = i["value"]
            else:
                out["bank_accounts"].append({"account": None, "ifsc": i["value"]})
        elif i["type"] == "upi":
            out["upi_ids"].append(i["value"])
        elif i["type"] == "mobile":
            out["mobiles"].append(i["value"])
        else:
            out["links"].append(i["value"])
    return out


def classify(transcript):
    """Scam type, impersonated agency and a one-line summary, from the caller's side of the call."""
    caller = "\n".join(text for who, text in transcript if who != "persona")
    try:
        answer = groq(os.environ.get("SCAMMER_MODEL", "openai/gpt-oss-20b"), [{"role": "user", "content":
                      f"Phone call transcript, caller's side only:\n{caller}\n\nReturn JSON with keys scam_type "
                      f"(one of {SCAM_TYPES}), impersonated_agency (string or null) and summary (one English "
                      "sentence on what the caller wanted)."}], max_tokens=600, response_format={"type": "json_object"})
        data = json.loads(answer)
        if data.get("scam_type") not in SCAM_TYPES:
            data["scam_type"] = "other"
        return {k: data.get(k) for k in ("scam_type", "impersonated_agency", "summary")}
    except Exception as e:  # the report is still worth saving without a classification
        return {"scam_type": None, "impersonated_agency": None, "summary": None, "classification_error": str(e)}


def build_report(call_report, transcript, persona, started_at, synthetic=True, classify_with=classify):
    started = datetime.fromtimestamp(started_at, IST)
    return {
        "report_id": started.strftime("%Y%m%d-%H%M%S"),
        "category": "Online financial fraud: attempted, intercepted by a honeypot line",
        "incident": {"started": started.isoformat(timespec="seconds"), "duration_sec": call_report["duration"],
                     "channel": "Inbound voice call", "answered_by": persona},
        "caller_classified_as": call_report["mode"],
        "scam": classify_with(transcript),
        "suspect_identifiers": suspects(call_report["identifiers"]),
        "stage_timings_sec": call_report["stage_times"],
        "payment_fail_loops": call_report["payment_fails"],
        "transcript": [{"speaker": who, "text": text} for who, text in transcript],
        "note": ("Role-played scammer and synthetic identifiers." if synthetic else
                 "Identifiers are validated for format only; confirm before acting on them."),
    }


def save(report):
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"{report['report_id']}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return path
