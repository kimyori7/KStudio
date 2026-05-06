"""KStudio MCP (Model Context Protocol) 통합.

LLM CLI (Claude Code / Gemini CLI / OpenAI Codex 등) 가 KStudio 를 자연어로
제어할 수 있게 한다. 구조:

    [LLM CLI]   ←stdio MCP→   [kstudio_mcp.py]   ←localhost HTTP→   [KStudio.exe]
                                  (stdio 서버)        (브리지)         (UI 프로세스)

KStudio 는 GUI 프로세스라 stdio MCP 의 1:1 자식 관계와 안 맞음 → HTTP 브리지로
디커플링. 사용자가 환경설정에서 토글하면 시작 시 `127.0.0.1:<port>` 에 서버
띄움. 인증은 보안 토큰(32자 hex) 으로 — 외부에서 임의 호출 차단.

Stage 1 (현재): HTTP 브리지 + UI 스레드 마샬링 + 1개 read-only 도구
(`get_current_image_path`). 후속 단계 — 더 많은 도구, stdio MCP 서버, CLI 자동
등록, 임베드 터미널 도크.
"""
