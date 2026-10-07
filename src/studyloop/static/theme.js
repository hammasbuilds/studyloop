try { var t = localStorage.getItem("sl-theme"); if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; } catch (e) {}
