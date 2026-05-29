// 미리보기 렌더 오케스트레이션. Python 이 window.updateMarkdown(html, docDir, revision)
// 으로 "이미 렌더된 HTML 문자열"을 주입한다 (Phase 1: markdown→html 은 Python).
(function () {
  "use strict";
  var latestRevision = -1;

  function el(id) { return document.getElementById(id); }

  function resolveRelative(url, docDir) {
    if (!docDir) return url;
    if (/^([a-z]+:|\/\/|#|data:)/i.test(url)) return url; // 절대/data/anchor 그대로
    var base = docDir.replace(/\\/g, "/");
    if (base.charAt(base.length - 1) !== "/") base += "/";
    return "file:///" + base + url;
  }

  function rewriteAssets(root, docDir) {
    var imgs = root.querySelectorAll("img[src]");
    for (var i = 0; i < imgs.length; i++) {
      imgs[i].setAttribute("src", resolveRelative(imgs[i].getAttribute("src"), docDir));
    }
  }

  // --- 스크롤 동기화 (나란히 모드) ---
  // 세로 스크롤 가능한 최대 픽셀. body/documentElement 양쪽을 보고 큰 값을 씀.
  function scrollMax() {
    var d = document.documentElement, b = document.body;
    var h = Math.max(d ? d.scrollHeight : 0, b ? b.scrollHeight : 0);
    return Math.max(0, h - window.innerHeight);
  }

  // 프로그램적 스크롤 직후의 scroll 이벤트(echo)를 무시할 시각. 무시 안 하면
  // Python→preview→Python 무한 루프. (Python 쪽 _syncing 은 동기 경로만 막음.)
  var suppressUntil = 0;

  window.setScrollRatio = function (r) {
    var max = scrollMax();
    suppressUntil = Date.now() + 150;   // 이 set 이 유발할 echo 무시
    window.scrollTo(0, max > 0 ? max * r : 0);
  };

  var ticking = false;
  window.addEventListener("scroll", function () {
    if (Date.now() < suppressUntil) return;   // echo 억제
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(function () {
      ticking = false;
      var max = scrollMax();
      var r = max > 0 ? window.scrollY / max : 0;
      // Python(_LoggingPage.javaScriptConsoleMessage) 이 "KSCROLL:" 접두사로 파싱.
      console.log("KSCROLL:" + r.toFixed(4));
    });
  }, { passive: true });

  window.updateMarkdown = function (html, docDir, revision) {
    if (revision < latestRevision) return; // stale drop
    latestRevision = revision;
    var root = el("content");
    try {
      el("error").textContent = "";
      root.innerHTML = html;
      rewriteAssets(root, docDir);
      // Phase 2: mermaid / KaTeX 재실행 지점 (현재는 no-op).
    } catch (e) {
      el("error").textContent = "render error: " + e;
    }
  };

  // 외부 링크는 미리보기 안에서 네비게이션하지 않음 (Python 이 acceptNavigationRequest 로
  // 시스템 브라우저로 보냄). 여기선 기본 동작 막기만.
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]");
    if (a) e.preventDefault();
  });
})();
