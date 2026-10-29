from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from rag_engine import (
    get_chunk,
    get_clause,
    list_standards,
    lookup_material,
    lookup_section,
    search_standards,
)


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        try:
            if parsed.path == "/health":
                self._send_json({"status": "ok"})
            elif parsed.path == "/standards":
                self._send_json(list_standards())
            elif parsed.path == "/search":
                self._send_json(
                    search_standards(
                        params.get("q", ""),
                        int(params.get("top_k", "5")),
                        params.get("standard_id"),
                    )
                )
            elif parsed.path == "/clause":
                self._send_json(
                    get_clause(
                        params.get("standard_id", ""),
                        params.get("clause_no", ""),
                    )
                )
            elif parsed.path == "/material":
                self._send_json(
                    lookup_material(
                        params.get("grade", ""),
                        float(params.get("thickness", "0")),
                    )
                )
            elif parsed.path == "/section":
                self._send_json(lookup_section(params.get("section_id", "")))
            elif parsed.path == "/chunk":
                result = get_chunk(params.get("id", ""))
                self._send_json(result or {}, 200 if result else 404)
            else:
                self._send_json({"error": "Not found"}, 404)
        except Exception as error:  # noqa: BLE001
            self._send_json({"error": str(error)}, 500)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/search":
            try:
                result = search_standards(
                    payload.get("query", ""),
                    int(payload.get("top_k", 5)),
                    payload.get("standard_id"),
                )
                self._send_json(result)
            except Exception as error:  # noqa: BLE001
                self._send_json({"error": str(error)}, 500)
        else:
            self._send_json({"error": "Not found"}, 404)

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("SteelMind standards API: http://127.0.0.1:8765", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
