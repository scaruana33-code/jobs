"""Weekly Gmail sync: detect job-search progress, update data/applications.json,
and email yourself a summary. Classification is keyword-based, so treat it as a
good first pass and correct anything odd in the dashboard."""
import base64, datetime as dt, hashlib, json, os, re
from email.mime.text import MIMEText
from email.utils import parseaddr
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DATA = Path(__file__).resolve().parent.parent / "data" / "applications.json"
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "14"))
SEND_SUMMARY = os.environ.get("SEND_SUMMARY", "1") == "1"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/gmail.send"]

RANK = {"applied": 0, "screen": 1, "round1": 2, "round2": 3, "round3": 4, "final": 5, "offer": 6}
INTERVIEW = ["screen", "round1", "round2", "round3", "final"]
ATS_DOMAINS = ("greenhouse", "lever.co", "ashby", "workday", "icims", "smartrecruiters",
               "jobvite", "taleo", "dayforce", "successfactors", "workable", "bamboohr")
NOISE = re.compile(r"\b(careers?|recruiting|talent( acquisition)?|jobs?|hr|no-?reply|team|notifications?|hiring)\b", re.I)

QUERY = (
    'newer_than:{d}d (subject:(application OR applying OR "thank you for applying" OR interview '
    'OR "phone screen" OR "next steps" OR offer OR "your candidacy" OR "your application") '
    'OR from:(greenhouse.io OR lever.co OR ashbyhq.com OR myworkday.com OR icims.com '
    'OR smartrecruiters.com OR jobvite.com OR linkedin.com))'
)


def classify(text: str):
    t = text.lower()
    if re.search(r"pleased to offer|offer letter|job offer|extend(ing)? (you )?an offer", t):
        return "offer"
    if re.search(r"unfortunately|not (be )?moving forward|decided to (move|proceed)[a-z ]* with (other|another)"
                 r"|no longer (available|under consideration)|regret to inform|will not be (moving|proceeding)", t):
        return "rejected"
    if re.search(r"final (round|interview)|on-?site|panel interview|super ?day", t):
        return "final"
    if re.search(r"(third|3rd) (round|interview)|round 3", t):
        return "round3"
    if re.search(r"(second|2nd) (round|interview)|round 2", t):
        return "round2"
    if re.search(r"(phone|first|1st) (round|interview|screen)|hiring manager (interview|call)|round 1|technical interview", t):
        return "round1"
    if re.search(r"recruiter (screen|call|chat)|intro(ductory)? (call|chat)|schedule a (call|chat)|"
                 r"invite you to (a |an )?(call|interview|chat)|interview (invitation|confirmation|scheduled)", t):
        return "screen"
    if re.search(r"thank you for (applying|your application|your interest)|received your application|"
                 r"application (received|submitted)|we.ve received your|your application (was sent|to)", t):
        return "applied"
    return None


def body_text(payload):
    parts = [payload] + payload.get("parts", [])
    out = []
    while parts:
        p = parts.pop(0)
        parts.extend(p.get("parts", []))
        if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
            out.append(base64.urlsafe_b64decode(p["body"]["data"]).decode("utf-8", "ignore"))
    return " ".join(out)[:4000]


def company_role(subject, sender_name, sender_addr):
    m = re.match(r"your application to (.+?) at (.+)$", subject.strip(), re.I)  # LinkedIn format
    if m:
        return m.group(2).strip(), m.group(1).strip()
    company = None
    m = re.search(r"\b(?:at|with|to)\s+([A-Z][\w&.\-]*(?:\s[A-Z][\w&.\-]*){0,3})", subject)
    if m:
        company = m.group(1).strip()
    domain = sender_addr.split("@")[-1].lower()
    if not company:
        name = NOISE.sub("", sender_name).strip(" -|,")
        company = name or domain.split(".")[-2].title()
    role = ""
    m = re.search(r"(?:for|:|-|–)\s+(?:the\s+)?(.+?)(?:\s+(?:at|position|role|opportunity)\b|\s*[-|(]|$)", subject)
    if m and 3 < len(m.group(1)) < 80:
        role = m.group(1).strip()
    return company, role


def make_id(company, role, date):
    return hashlib.md5(f"{company}|{role}|{date}".lower().encode()).hexdigest()[:8]


def upsert(apps, company, role, source, date, stage):
    same = [a for a in apps if a["company"].lower() == company.lower()]
    match = None
    if role:
        match = next((a for a in same if a["role"].lower() == role.lower()), None)
    elif same:
        match = sorted(same, key=lambda a: a["dateApplied"])[-1]
    if not match:
        entry = {"id": make_id(company, role, date), "company": company, "role": role or "Unknown role",
                 "source": source, "dateApplied": date, "stage": "applied", "stageDate": None}
        apps.append(entry)
        match = entry
    cur = match["stage"]
    rank = -1 if stage == "rejected" else RANK[stage]
    cur_rank = -1 if cur == "rejected" else RANK[cur]
    if rank > cur_rank or (stage == "rejected" and cur == "applied"):
        match["stage"] = stage
        match["stageDate"] = None if stage == "applied" else date
    # Rejections never overwrite a reached interview stage, so rounds stay counted.


def summary(apps):
    today = dt.date.today()
    since = (today - dt.timedelta(days=7)).isoformat()
    applied = [a for a in apps if a["dateApplied"] >= since]
    events = [a for a in apps if a["stage"] in INTERVIEW and (a["stageDate"] or "") >= since]
    offers = [a for a in apps if a["stage"] == "offer" and (a["stageDate"] or "") >= since]
    lines = [f"Job search summary, week ending {today.isoformat()}", "",
             f"Applications submitted: {len(applied)}",
             f"Interview events: {len(events)}",
             f"Offers: {len(offers)}", "", "Conversion by source (all time):"]
    for src in ("ats", "linkedin", "networking", "recruiter"):
        pool = [a for a in apps if a["source"] == src]
        if not pool:
            lines.append(f"  {src:<11} no applications"); continue
        iv = sum(1 for a in pool if a["stage"] in INTERVIEW or a["stage"] == "offer")
        of = sum(1 for a in pool if a["stage"] == "offer")
        lines.append(f"  {src:<11} {len(pool)} applied, {iv / len(pool):.0%} interviewed, {of / len(pool):.0%} offer")
    rounds = sum(RANK[a["stage"]] for a in apps if a["stage"] in RANK and a["stage"] != "applied")
    lines += ["", f"Avg. interview rounds per application: {rounds / len(apps):.2f}" if apps else ""]
    return "\n".join(lines)


def main():
    creds = Credentials(None, refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
                        client_id=os.environ["GOOGLE_CLIENT_ID"],
                        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
                        token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES)
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)

    doc = json.loads(DATA.read_text()) if DATA.exists() else {"items": []}
    apps = doc["items"] if isinstance(doc, dict) else doc

    ids, token = [], None
    while True:
        r = gmail.users().messages().list(userId="me", q=QUERY.format(d=LOOKBACK_DAYS),
                                          maxResults=100, pageToken=token).execute()
        ids += [m["id"] for m in r.get("messages", [])]
        token = r.get("nextPageToken")
        if not token or len(ids) >= 500:
            break

    msgs = [gmail.users().messages().get(userId="me", id=i, format="full").execute() for i in ids]
    msgs.sort(key=lambda m: int(m["internalDate"]))

    for m in msgs:
        h = {x["name"].lower(): x["value"] for x in m["payload"]["headers"]}
        subject = h.get("subject", "")
        name, addr = parseaddr(h.get("from", ""))
        stage = classify(subject + " " + m.get("snippet", "") + " " + body_text(m["payload"]))
        if not stage:
            continue
        date = dt.datetime.fromtimestamp(int(m["internalDate"]) / 1000, dt.timezone.utc).date().isoformat()
        company, role = company_role(subject, name, addr)
        if "linkedin.com" in addr.lower():
            source = "linkedin"
        elif stage in INTERVIEW and not any(d in addr.lower() for d in ATS_DOMAINS):
            source = "recruiter"   # first seen via a human interview email, no prior application
        else:
            source = "ats"
        upsert(apps, company, role, source, date, stage)

    DATA.write_text(json.dumps({"updated": dt.datetime.now(dt.timezone.utc).isoformat(), "items": apps}, indent=1))
    print(f"Scanned {len(msgs)} messages; {len(apps)} applications tracked.")

    if SEND_SUMMARY:
        me = gmail.users().getProfile(userId="me").execute()["emailAddress"]
        mail = MIMEText(summary(apps))
        mail["to"], mail["from"], mail["subject"] = me, me, "Your weekly job-search summary"
        raw = base64.urlsafe_b64encode(mail.as_bytes()).decode()
        gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
        print("Summary email sent to", me)


if __name__ == "__main__":
    main()
