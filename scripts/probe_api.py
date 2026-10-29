"""Check configured endpoints without logging credentials, prompts or response bodies."""
import json
import urllib.error
import urllib.request
from pathlib import Path


def main():
    config = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            config[k] = v.strip().strip('"')
    base = config.get("KB_CHAT_BASE_URL", "").rstrip("/")
    key = config.get("KB_CHAT_API_KEY", "")
    for endpoint in ("/models", "/embedding", "/embeddings"):
        data = None if endpoint == "/models" else json.dumps({
            "model": config.get("KB_EMBEDDING_MODEL", "qwen3.7-text-embedding") or "qwen3.7-text-embedding",
            "input": ["knowledge service connection check"]}).encode()
        request = urllib.request.Request(base + endpoint, data=data, headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = json.load(response)
                if endpoint == "/models":
                    print(json.dumps({"endpoint": endpoint, "status": response.status,
                        "models": [m.get("id") for m in body.get("data", [])]}, ensure_ascii=False))
                else:
                    vector = body.get("data", [{}])[0].get("embedding", [])
                    print(json.dumps({"endpoint": endpoint, "status": response.status, "dimensions": len(vector)}))
        except urllib.error.HTTPError as error:
            print(json.dumps({"endpoint": endpoint, "status": error.code}))
        except Exception as error:
            print(json.dumps({"endpoint": endpoint, "error_type": type(error).__name__}))


if __name__ == "__main__":
    main()
