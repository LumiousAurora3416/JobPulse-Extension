/**
 * JobPulse 配置页 — 将飞书凭证保存到 chrome.storage.local
 * 配置在整个扩展内共享（popup.js / dashboard.js 均可读取）
 */
document.addEventListener("DOMContentLoaded", () => {
  // 加载已有配置回显
  chrome.storage.local.get(["feishuConfig"], (result) => {
    if (result.feishuConfig) {
      const c = result.feishuConfig;
      document.getElementById("appId").value = c.appId || "";
      document.getElementById("appSecret").value = c.appSecret || "";
      document.getElementById("appToken").value = c.appToken || "";
      document.getElementById("tableId").value = c.tableId || "";
    }
  });

  document.getElementById("saveBtn").addEventListener("click", saveConfig);
});

function showMessage(text, ok) {
  const el = document.getElementById("message");
  el.textContent = text;
  el.className = "msg " + (ok ? "ok" : "err");
}

function saveConfig() {
  const config = {
    appId: document.getElementById("appId").value.trim(),
    appSecret: document.getElementById("appSecret").value.trim(),
    appToken: document.getElementById("appToken").value.trim(),
    tableId: document.getElementById("tableId").value.trim(),
  };

  const missing = Object.entries(config)
    .filter(([_, v]) => !v)
    .map(([k]) => k);
  if (missing.length) {
    showMessage("请填写完整：" + missing.join("、"), false);
    return;
  }

  chrome.storage.local.set({ feishuConfig: config }, () => {
    showMessage("✅ 配置已保存！可以关闭此页面，回到插件弹窗使用", true);
  });
}
