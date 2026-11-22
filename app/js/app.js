(function () {
  const root = document.getElementById("screen");
  const tabbar = document.getElementById("tabbar");
  const toastEl = document.getElementById("toast");

  let S = null;
  const state = {
    screen: "intro",
    newsId: null,
    schedId: null,
    filter: "Semua",
    quizIndex: 0,
    quizScore: 0,
    quizLocked: false,
    quizPicked: null,
    votePick: null,
    voteDone: false
  };

  const ICO = {
    berita: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="5" width="16" height="14" rx="2"/><path d="M8 9h8M8 13h5"/></svg>',
    jadwal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M8 3v4M16 3v4"/></svg>',
    kuis: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.8.4-1.5 1-1.5 2v.2"/><circle cx="12" cy="17" r=".8" fill="currentColor" stroke="none"/></svg>',
    vote: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3.2l2.1 5.3 5.7.4-4.4 3.6 1.4 5.5L12 14.8 6.2 18l1.4-5.5L3.2 8.9l5.7-.4L12 3.2z"/></svg>'
  };

  const tg = window.Telegram && window.Telegram.WebApp;

  function tgAtLeast(ver) {
    try {
      return !!(tg && tg.isVersionAtLeast && tg.isVersionAtLeast(ver));
    } catch (e) {
      return false;
    }
  }

  function applyTheme() {
    const docEl = document.documentElement;
    let dark = false;
    if (tg && tg.colorScheme) dark = tg.colorScheme === "dark";
    else if (window.matchMedia) dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (params().get("theme")) dark = params().get("theme") === "dark";
    docEl.classList.toggle("dark", dark);
    const tp = (tg && tg.themeParams) || {};
    if (tp.bg_color) docEl.style.setProperty("--tg-bg", tp.bg_color);
    if (tp.secondary_bg_color) docEl.style.setProperty("--tg-bg2", tp.secondary_bg_color);
    if (tp.text_color) docEl.style.setProperty("--tg-text", tp.text_color);
    if (tp.hint_color) docEl.style.setProperty("--tg-hint", tp.hint_color);
    if (tgAtLeast("6.1")) {
      try {
        const bg = getComputedStyle(docEl).getPropertyValue("--bg").trim();
        tg.setHeaderColor(bg);
        tg.setBackgroundColor(bg);
      } catch (e) {}
    }
  }

  function setupTelegram() {
    applyTheme();
    if (!tg) return;
    try {
      tg.ready();
      tg.expand();
    } catch (e) {}
    try { tg.onEvent && tg.onEvent("themeChanged", applyTheme); } catch (e) {}
    if (tgAtLeast("6.1") && tg.BackButton && tg.BackButton.onClick) {
      tg.BackButton.onClick(goBack);
    }
  }

  function syncBackButton() {
    if (!tgAtLeast("6.1") || !tg.BackButton) return;
    const stacked = { detail: 1, "jadwal-detail": 1, "kuis-play": 1, "kuis-result": 1 };
    try {
      if (stacked[state.screen]) tg.BackButton.show();
      else tg.BackButton.hide();
    } catch (e) {}
  }

  function goBack() {
    if (state.screen === "detail") go("berita");
    else if (state.screen === "jadwal-detail") go("jadwal");
    else if (state.screen === "kuis-play" || state.screen === "kuis-result") go("kuis");
    else if (tg && tg.close) tg.close();
  }

  function params() {
    return new URLSearchParams(location.search);
  }

  function applyParams() {
    const p = params();
    try {
      const sp = tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param;
      if (sp && /^[A-Za-z0-9_-]{1,64}$/.test(sp)) {
        state.screen = "detail";
        state.newsId = sp;
      }
    } catch (e) {}
    const sc = p.get("screen");
    if (sc) state.screen = sc;
    if (p.get("id")) state.newsId = p.get("id");
    if (p.get("sid")) state.schedId = p.get("sid");
    if (p.get("q")) state.quizIndex = Math.max(0, parseInt(p.get("q"), 10) || 0);
    if (p.get("score") != null) state.quizScore = parseInt(p.get("score"), 10) || 0;
    if (p.get("filter")) state.filter = p.get("filter");
    if (p.get("pick")) state.votePick = p.get("pick");
    if (p.get("voted") === "1") state.voteDone = true;
    if (p.get("choice") != null) {
      state.quizPicked = parseInt(p.get("choice"), 10);
      if (p.get("locked") === "1") state.quizLocked = true;
    }
  }

  function voteKey() {
    return "kabarunnie-vote-" + (S && S.vote && S.vote.id ? S.vote.id : "none");
  }

  function initVoteFromStorage() {
    try {
      const saved = localStorage.getItem(voteKey());
      if (saved) {
        state.voteDone = true;
        state.votePick = saved;
      }
    } catch (e) {}
  }

  function go(screen, extra) {
    state.screen = screen;
    if (extra) Object.assign(state, extra);
    render();
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.remove("hidden");
    clearTimeout(toast.t);
    toast.t = setTimeout(function () {
      toastEl.classList.add("hidden");
    }, 1800);
  }

  function openTelegramOrWeb(url) {
    if (tg && tg.openTelegramLink && url.indexOf("t.me") !== -1) {
      try {
        tg.openTelegramLink(url);
        return;
      } catch (e) {}
    }
    if (tg && tg.openLink) {
      try {
        tg.openLink(url);
        return;
      } catch (e) {}
    }
    window.open(url, "_blank", "noopener");
  }

  function share(text) {
    const url = S.channelUrl;
    const full = text + "\n" + url;
    const shareUrl =
      "https://t.me/share/url?url=" +
      encodeURIComponent(url) +
      "&text=" +
      encodeURIComponent(text);
    if (tg && tg.openTelegramLink) {
      try {
        tg.openTelegramLink(shareUrl);
        return;
      } catch (e) {}
    }
    if (navigator.share) {
      navigator.share({ text: full }).catch(function () {
        openTelegramOrWeb(shareUrl);
      });
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(full).then(function () {
        toast("Teks disalin. Siap dibagikan.");
      }).catch(function () {
        openTelegramOrWeb(shareUrl);
      });
      return;
    }
    openTelegramOrWeb(shareUrl);
  }

  function openChannel() {
    openTelegramOrWeb(S.channelUrl);
  }

  function avatar(item) {
    return (
      '<div class="avatar" style="background:' +
      escapeHtml(item.color) +
      '">' +
      escapeHtml(item.initial) +
      "</div>"
    );
  }

  function badge(item) {
    const cls = item.badge === "rumor" ? "badge-rumor" : "badge-resmi";
    return '<span class="badge ' + cls + '">' + escapeHtml(item.badgeLabel) + "</span>";
  }

  function tabbarHtml(active) {
    const tabs = [
      ["berita", "Berita"],
      ["jadwal", "Jadwal"],
      ["kuis", "Kuis"],
      ["vote", "Vote"]
    ];
    return tabs
      .map(function (t) {
        const on = t[0] === active ? " on" : "";
        return (
          '<button class="tab' +
          on +
          '" data-go="' +
          t[0] +
          '"><span class="ico">' +
          ICO[t[0]] +
          "</span>" +
          t[1] +
          "</button>"
        );
      })
      .join("");
  }

  function ctaSubscribe(label) {
    return (
      '<button class="btn btn-primary" data-act="subscribe">' +
      (label || "Gabung channel " + S.handle) +
      "</button>"
    );
  }

  function joinChip() {
    return '<button class="join-chip" data-act="subscribe">Gabung</button>';
  }

  function showTabs(active) {
    tabbar.classList.remove("hidden");
    tabbar.innerHTML = tabbarHtml(active);
  }

  function hideTabs() {
    tabbar.classList.add("hidden");
    tabbar.innerHTML = "";
  }

  function renderIntro() {
    hideTabs();
    root.className = "screen is-intro";
    root.innerHTML =
      '<section class="intro screen-fade">' +
      '<div class="intro-hero">' +
      '<div class="mark">U</div>' +
      "<h1>Kabar<br>Unnie</h1>" +
      '<p class="lead">Berita girl group dan gosip hiburan Korea, dalam bahasa Indonesia. Singkat, bersumber, dan jelas mana yang belum dikonfirmasi.</p>' +
      '<div class="pills">' +
      '<span class="pill">Berita harian</span>' +
      '<span class="pill">Jadwal comeback</span>' +
      '<span class="pill">Kuis &amp; vote</span>' +
      "</div></div>" +
      '<div class="intro-actions">' +
      '<button class="btn btn-primary" data-go="berita">Mulai</button>' +
      '<p class="fineprint">' +
      escapeHtml(S.disclaimer) +
      "</p></div></section>";
  }

  function hero(n, size) {
    const m = n.media;
    if (!m) return "";
    if (state.playing === n.id && size === "big") {
      return (
        '<div class="hero hero-' + size + ' is-embed"><iframe src="https://www.youtube-nocookie.com/embed/' +
        encodeURIComponent(m.id) +
        '?autoplay=1&playsinline=1" title="' + escapeHtml(n.title) +
        '" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div>'
      );
    }
    return (
      '<div class="hero hero-' + size + '" role="button" tabindex="0" data-act="play" data-id="' +
      escapeHtml(n.id) + '" data-url="' + escapeHtml(m.url) + '" aria-label="Putar video resmi">' +
      '<img src="' + escapeHtml(m.thumb) + '" data-fallback="' + escapeHtml(m.thumbFallback) +
      '" alt="Thumbnail video resmi ' + escapeHtml(n.group) + '" loading="lazy" referrerpolicy="no-referrer">' +
      '<span class="hero-shade"></span>' +
      '<span class="play" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></span>' +
      '<span class="hero-src">▶ YouTube · ' + escapeHtml(m.channel) + ' (resmi)</span>' +
      "</div>"
    );
  }

  function officialLinks(n) {
    let h = '<div class="off-links">';
    if (n.media) h += '<a href="' + escapeHtml(n.media.url) + '" data-act="open-source" data-url="' + escapeHtml(n.media.url) + '">▶ Video resmi · ' + escapeHtml(n.media.channel) + "</a>";
    if (n.xPost) h += '<a href="' + escapeHtml(n.xPost.url) + '" data-act="open-source" data-url="' + escapeHtml(n.xPost.url) + '">𝕏 Post resmi · ' + escapeHtml(n.xPost.handle) + "</a>";
    return h + "</div>";
  }

  function renderBerita() {
    showTabs("berita");
    root.className = "screen";
    const cards = S.news
      .map(function (n, i) {
        return (
          '<article class="card' + (i === 0 ? " card-lead" : "") + '">' +
          hero(n, i === 0 ? "lead" : "sm") +
          '<div class="card-body" role="button" tabindex="0" data-news="' + escapeHtml(n.id) + '">' +
          '<div class="card-hd"><span class="group-tag">' + escapeHtml(n.group) + "</span>" +
          '<span class="time">' + escapeHtml(n.time) + "</span>" + badge(n) + "</div>" +
          "<h3>" + escapeHtml(n.title) + "</h3>" +
          '<p class="hook">' + escapeHtml(n.hook) + "</p>" +
          '<span class="more">Baca selengkapnya →</span>' +
          "</div></article>"
        );
      })
      .join("");
    root.innerHTML =
      '<div class="screen-fade"><div class="top"><div class="brand"><span class="eyebrow">Berita girl group</span><div class="wordmark">Kabar Unnie</div></div>' +
      joinChip() +
      "</div>" +
      '<div class="section-title"><h2>Hari ini di Korea</h2><span>' +
      escapeHtml(S.todayLabel.replace(/^[^,]+, /, "")) +
      "</span></div>" +
      '<div class="cards">' + cards + "</div>" +
      '<div class="cta-row">' + ctaSubscribe() +
      '<p class="fineprint">' + escapeHtml(S.mediaPolicy || "") + "<br>" + escapeHtml(S.disclaimer) + "</p></div></div>";
  }

  function renderDetail() {
    const n = S.news.find(function (x) { return x.id === state.newsId; }) || S.news[0];
    showTabs("berita");
    root.className = "screen";
    const rumor =
      n.badge === "rumor"
        ? '<div class="warn-note">Label <strong>Belum dikonfirmasi</strong> berarti kabar ini belum diakui agensi atau sumber resmi. Jangan bagikan sebagai fakta.</div>'
        : "";
    const paras = n.body.map(function (p) { return "<p>" + escapeHtml(p) + "</p>"; }).join("");
    root.innerHTML =
      '<div class="screen-fade"><div class="back-row"><button type="button" data-act="back" aria-label="Kembali">←</button><span class="label">Berita</span></div>' +
      '<div class="detail-hero">' + hero(n, "big") + "</div>" +
      '<article class="detail">' +
      '<div class="detail-kicker"><span class="group-tag">' + escapeHtml(n.group) + "</span>" + badge(n) +
      '<span class="time">' + escapeHtml(n.time) + "</span></div>" +
      "<h2>" + escapeHtml(n.title) + "</h2>" +
      rumor +
      '<div class="body">' + paras + "</div>" +
      officialLinks(n) +
      '<div class="source-box"><strong>Sumber berita: ' + escapeHtml(n.sourceName) +
      "</strong>Ditulis ulang singkat. Artikel utuh tidak disalin. Gambar dari pratinjau video resmi.</div>" +
      '<div class="actions">' +
      '<button class="btn btn-primary" data-act="share-news" data-title="' + escapeHtml(n.title) + '">Bagikan</button>' +
      '<button class="btn btn-ghost" data-act="open-source" data-url="' + escapeHtml(n.sourceUrl) + '">Baca sumber</button>' +
      ctaSubscribe("Gabung channel untuk update harian") +
      "</div></article></div>";
  }

  function renderJadwal() {
    showTabs("jadwal");
    root.className = "screen";
    const groups = ["Semua"].concat(
      S.schedule
        .map(function (s) { return s.group; })
        .filter(function (g, i, a) { return a.indexOf(g) === i; })
    );
    const chips = groups
      .map(function (g) {
        return (
          '<button class="chip' +
          (state.filter === g ? " on" : "") +
          '" data-filter="' +
          escapeHtml(g) +
          '">' +
          escapeHtml(g) +
          "</button>"
        );
      })
      .join("");
    const items = S.schedule.filter(function (s) {
      return state.filter === "Semua" || s.group === state.filter;
    });
    let html =
      '<div class="screen-fade"><div class="top"><div class="brand"><span class="eyebrow">Tracker</span><div class="wordmark">Jadwal comeback</div></div>' +
      joinChip() +
      "</div>" +
      '<p class="pad" style="color:var(--muted);font-size:13px;margin-bottom:10px">Rilis yang sudah diumumkan, dengan tautan sumber.</p>' +
      '<div class="filter-row">' +
      chips +
      "</div>";
    let last = "";
    items.forEach(function (s) {
      if (s.date !== last) {
        html += '<div class="day-label">' + escapeHtml(s.date) + " · " + escapeHtml(s.when) + "</div>";
        last = s.date;
      }
      html +=
        '<button class="sched" data-sched="' +
        escapeHtml(s.id) +
        '">' +
        avatar(s) +
        '<div class="info"><div class="grp">' +
        escapeHtml(s.group) +
        "</div><h3>" +
        escapeHtml(s.title) +
        "</h3><p>" +
        escapeHtml(s.meta) +
        "</p></div></button>";
    });
    html +=
      '<div class="cta-row" style="margin-top:8px">' +
      ctaSubscribe("Ingatkan lewat channel") +
      '<p class="fineprint">Gabung channel supaya jadwal baru tidak ketinggalan.</p></div></div>';
    root.innerHTML = html;
  }

  function renderJadwalDetail() {
    const s = S.schedule.find(function (x) { return x.id === state.schedId; }) || S.schedule[0];
    showTabs("jadwal");
    root.className = "screen";
    root.innerHTML =
      '<div class="screen-fade"><div class="back-row"><button type="button" data-act="back" aria-label="Kembali">←</button><span class="label">Jadwal</span></div>' +
      '<article class="detail">' +
      '<div class="detail-kicker">' +
      avatar(s) +
      "<strong>" +
      escapeHtml(s.group) +
      "</strong></div>" +
      "<h2>" +
      escapeHtml(s.title) +
      "</h2>" +
      "<p>" +
      escapeHtml(s.date) +
      " · " +
      escapeHtml(s.when) +
      "</p>" +
      '<p class="hook" style="margin:8px 0 14px">' +
      escapeHtml(s.meta) +
      "</p>" +
      "<p>" +
      escapeHtml(s.note) +
      "</p>" +
      '<div class="source-box"><strong>' +
      escapeHtml(s.sourceName) +
      "</strong></div>" +
      '<div class="actions">' +
      '<button class="btn btn-ghost" data-act="open-source" data-url="' +
      escapeHtml(s.sourceUrl) +
      '">Baca sumber</button>' +
      ctaSubscribe("Ingatkan lewat channel") +
      "</div></article></div>";
  }

  function renderKuisHome() {
    showTabs("kuis");
    root.className = "screen";
    root.innerHTML =
      '<div class="screen-fade"><div class="top"><div class="brand"><span class="eyebrow">Harian</span><div class="wordmark">Kuis Unnie</div></div>' +
      joinChip() +
      "</div>" +
      '<div class="hero-card"><div class="kicker">5 soal</div><h2>' +
      escapeHtml(S.quiz.title) +
      "</h2><p>" +
      escapeHtml(S.quiz.subtitle) +
      "</p></div>" +
      '<div class="cta-row"><button class="btn btn-primary" data-act="quiz-start">Mulai kuis</button>' +
      '<p class="fineprint">Fakta publik (debut, agensi, berita minggu ini).</p></div></div>';
  }

  function renderKuisPlay() {
    const i = state.quizIndex;
    const q = S.quiz.questions[i];
    const total = S.quiz.questions.length;
    showTabs("kuis");
    root.className = "screen";
    const choices = q.choices
      .map(function (c, idx) {
        let cls = "choice";
        if (state.quizLocked && idx === q.answer) cls += " good";
        if (state.quizLocked && state.quizPicked === idx && idx !== q.answer) cls += " bad";
        if (!state.quizLocked && state.quizPicked === idx) cls += " on";
        return (
          '<button class="' +
          cls +
          '" data-choice="' +
          idx +
          '"' +
          (state.quizLocked ? " disabled" : "") +
          ">" +
          escapeHtml(c) +
          "</button>"
        );
      })
      .join("");
    const nextLabel = i === total - 1 ? "Lihat hasil" : "Lanjut";
    root.innerHTML =
      '<div class="screen-fade"><div class="back-row"><button type="button" data-act="back" aria-label="Kembali">←</button><span class="label">Kuis harian</span></div>' +
      '<div class="progress"><span>Soal ' +
      (i + 1) +
      " / " +
      total +
      "</span><span>Skor " +
      state.quizScore +
      "</span></div>" +
      '<div class="bar"><i style="width:' +
      Math.round(((i + (state.quizLocked ? 1 : 0)) / total) * 100) +
      '%"></i></div>' +
      '<div class="hero-card" style="margin-top:0"><h2 style="font-size:24px">' +
      escapeHtml(q.q) +
      "</h2></div>" +
      choices +
      '<div class="cta-row"><button class="btn btn-primary" data-act="quiz-next"' +
      (state.quizLocked ? "" : " disabled") +
      ">" +
      nextLabel +
      "</button></div></div>";
  }

  function renderKuisResult() {
    const total = S.quiz.questions.length;
    const score = state.quizScore;
    const comment =
      score <= 2 ? S.quiz.comments[0] : score <= 4 ? S.quiz.comments[1] : S.quiz.comments[2];
    showTabs("kuis");
    root.className = "screen";
    root.innerHTML =
      '<div class="screen-fade"><div class="top"><div class="brand"><span class="eyebrow">Hasil</span><div class="wordmark">Skor hari ini</div></div></div>' +
      '<div class="hero-card"><div class="kicker">Kuis harian</div>' +
      '<div class="score">' +
      score +
      "<span>/" +
      total +
      "</span></div><p>" +
      escapeHtml(comment) +
      "</p></div>" +
      '<div class="cta-row">' +
      '<button class="btn btn-primary" data-act="share-quiz">Bagikan skor</button>' +
      ctaSubscribe() +
      '<button class="btn btn-ghost" data-act="quiz-start">Coba lagi</button></div></div>';
  }

  function renderVote() {
    showTabs("vote");
    root.className = "screen";
    if (state.voteDone) {
      renderVoteResult();
      return;
    }
    const opts = S.vote.options
      .map(function (o) {
        return (
          '<button class="option' +
          (state.votePick === o.id ? " on" : "") +
          '" data-vote="' +
          escapeHtml(o.id) +
          '"><span class="dot"></span>' +
          escapeHtml(o.label) +
          "</button>"
        );
      })
      .join("");
    root.innerHTML =
      '<div class="screen-fade"><div class="top"><div class="brand"><span class="eyebrow">Mingguan</span><div class="wordmark">Vote Unnie</div></div>' +
      joinChip() +
      "</div>" +
      '<div class="hero-card"><div class="kicker">Polling minggu ini</div><h2>' +
      escapeHtml(S.vote.title) +
      "</h2><p>" +
      escapeHtml(S.vote.subtitle) +
      "</p></div>" +
      opts +
      '<div class="cta-row"><button class="btn btn-primary" data-act="vote-send"' +
      (state.votePick ? "" : " disabled") +
      ">Kirim suara</button>" +
      '<p class="fineprint">Satu suara per perangkat. Belum ada hitungan global — tidak ada angka yang kami buat-buat.</p></div></div>';
  }

  function renderVoteResult() {
    const picked = S.vote.options.find(function (o) { return o.id === state.votePick; });
    showTabs("vote");
    root.className = "screen";
    root.innerHTML =
      '<div class="screen-fade"><div class="top"><div class="brand"><span class="eyebrow">Suaramu</span><div class="wordmark">Vote Unnie</div></div></div>' +
      '<div class="hero-card"><div class="kicker">Tersimpan di perangkat ini</div><h2>' +
      escapeHtml(S.vote.title) +
      "</h2><p>Kamu memilih <strong>" +
      escapeHtml(picked ? picked.label : "—") +
      "</strong>. Hasil gabungan akan muncul setelah channel resmi berjalan.</p></div>" +
      '<div class="cta-row">' +
      '<button class="btn btn-primary" data-act="share-vote">Bagikan pilihan</button>' +
      ctaSubscribe() +
      "</div></div>";
  }

  function render() {
    if (!S) return;
    const map = {
      intro: renderIntro,
      berita: renderBerita,
      detail: renderDetail,
      jadwal: renderJadwal,
      "jadwal-detail": renderJadwalDetail,
      kuis: renderKuisHome,
      "kuis-play": renderKuisPlay,
      "kuis-result": renderKuisResult,
      vote: renderVote,
      "vote-result": renderVoteResult
    };
    (map[state.screen] || renderBerita)();
    syncBackButton();
    root.scrollTop = 0;
  }

  document.addEventListener("click", function (e) {
    const t = e.target.closest("[data-go], [data-news], [data-act], [data-filter], [data-choice], [data-vote], [data-sched]");
    if (!t) return;

    if (t.dataset.go) {
      go(t.dataset.go);
      return;
    }
    if (t.dataset.news) {
      go("detail", { newsId: t.dataset.news });
      return;
    }
    if (t.dataset.filter) {
      state.filter = t.dataset.filter;
      render();
      return;
    }
    if (t.dataset.sched) {
      go("jadwal-detail", { schedId: t.dataset.sched });
      return;
    }
    if (t.dataset.choice != null) {
      if (state.quizLocked) return;
      const idx = parseInt(t.dataset.choice, 10);
      state.quizPicked = idx;
      state.quizLocked = true;
      if (idx === S.quiz.questions[state.quizIndex].answer) state.quizScore += 1;
      render();
      return;
    }
    if (t.dataset.vote) {
      state.votePick = t.dataset.vote;
      render();
      return;
    }
    const act = t.dataset.act;
    if (act === "play") {
      e.preventDefault();
      if (state.screen === "detail" && t.dataset.id === state.newsId) {
        state.playing = t.dataset.id;
        render();
      } else {
        openTelegramOrWeb(t.dataset.url);
      }
      return;
    }
    if (act === "back") {
      goBack();
      return;
    }
    if (act === "subscribe") {
      openChannel();
      return;
    }
    if (act === "open-source") {
      e.preventDefault();
      openTelegramOrWeb(t.dataset.url);
      return;
    }
    if (act === "share-news") {
      share("Kabar Unnie: " + (t.dataset.title || ""));
      return;
    }
    if (act === "share-quiz") {
      share("Skor kuis Kabar Unnie aku " + state.quizScore + "/" + S.quiz.questions.length);
      return;
    }
    if (act === "share-vote") {
      share("Aku sudah vote di Kabar Unnie: " + S.vote.title);
      return;
    }
    if (act === "quiz-start") {
      state.quizIndex = 0;
      state.quizScore = 0;
      state.quizLocked = false;
      state.quizPicked = null;
      go("kuis-play");
      return;
    }
    if (act === "quiz-next") {
      if (!state.quizLocked) return;
      if (state.quizIndex >= S.quiz.questions.length - 1) {
        go("kuis-result");
        return;
      }
      state.quizIndex += 1;
      state.quizLocked = false;
      state.quizPicked = null;
      render();
      return;
    }
    if (act === "vote-send") {
      if (!state.votePick) return;
      state.voteDone = true;
      try { localStorage.setItem(voteKey(), state.votePick); } catch (err) {}
      go("vote-result");
    }
  });

  document.addEventListener("error", function (e) {
    const el = e.target;
    if (el && el.tagName === "IMG" && el.dataset.fallback && el.src !== el.dataset.fallback) el.src = el.dataset.fallback;
  }, true);

  function showBootError(msg) {
    hideTabs();
    root.className = "screen";
    root.innerHTML = '<div class="error-box">' + escapeHtml(msg) + "</div>";
  }

  setupTelegram();
  applyParams();
  root.innerHTML = '<div class="loading">Memuat kabar…</div>';

  fetch("data/content.json", { cache: "no-store" })
    .then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function (data) {
      S = data;
      if (!state.newsId && S.news[0]) state.newsId = S.news[0].id;
      if (!state.schedId && S.schedule[0]) state.schedId = S.schedule[0].id;
      initVoteFromStorage();
      applyParams();
      render();
      window.__kabarReady = true;
    })
    .catch(function (err) {
      window.__kabarError = String(err && err.message ? err.message : err);
      showBootError("Tidak bisa memuat kabar. Periksa koneksi, lalu buka lagi.");
    });
})();
