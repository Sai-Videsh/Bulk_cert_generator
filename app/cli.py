"""CLI: run the API or drive it (submit jobs, check status, download). stdlib-only client."""
import argparse
import json
import sys
import urllib.request


def _api(base: str, method: str, path: str, body: dict | None = None, headers: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode() or "{}"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        print(exc.read().decode(), file=sys.stderr)
        raise SystemExit(f"HTTP {exc.code}")


def cmd_serve(args):
    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


def cmd_create_job(args):
    with open(args.file) as f:
        payload = json.load(f)
    headers = {"Idempotency-Key": args.idempotency_key} if args.idempotency_key else {}
    status, out = _api(args.base_url, "POST", "/api/v1/jobs", payload, headers)
    print(json.dumps(out, indent=2, default=str))
    print(f"HTTP {status}  -> poll: python -m app.cli job-status {out.get('id')} --base-url {args.base_url}")


def cmd_job_status(args):
    status, out = _api(args.base_url, "GET", f"/api/v1/jobs/{args.job_id}")
    print(json.dumps(out, indent=2, default=str))


def cmd_download(args):
    url = f"{args.base_url.rstrip('/')}/api/v1/jobs/{args.job_id}/download"
    urllib.request.urlretrieve(url, args.out)
    print(f"saved -> {args.out}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bulk-certs", description="Bulk Certificate Generator CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the API server")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(func=cmd_serve)
    c = sub.add_parser("create-job", help="submit a bulk job from a JSON file (see sample_job.json)")
    c.add_argument("--file", required=True)
    c.add_argument("--base-url", default="http://127.0.0.1:8000")
    c.add_argument("--idempotency-key", default=None)
    c.set_defaults(func=cmd_create_job)
    j = sub.add_parser("job-status", help="fetch job status/progress")
    j.add_argument("job_id")
    j.add_argument("--base-url", default="http://127.0.0.1:8000")
    j.set_defaults(func=cmd_job_status)
    d = sub.add_parser("download", help="download a job as ZIP")
    d.add_argument("job_id")
    d.add_argument("--out", default="certificates.zip")
    d.add_argument("--base-url", default="http://127.0.0.1:8000")
    d.set_defaults(func=cmd_download)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
