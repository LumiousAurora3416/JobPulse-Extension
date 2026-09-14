/**
 * JobPulse 数据看板 — 从飞书多维表格拉取数据，用 Chart.js 渲染图表
 * 配置从 chrome.storage.local 读取（用户在 setup.html 中填入）
 */

let FEISHU = null;
const TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal";

function recordUrl(pageSize, pageToken) {
  var u = "https://open.feishu.cn/open-apis/bitable/v1/apps/" + FEISHU.appToken +
    "/tables/" + FEISHU.tableId + "/records?page_size=" + (pageSize || 100);
  if (pageToken) u += "&page_token=" + encodeURIComponent(pageToken);
  return u;
}

// ── API helpers ──

async function getTenantAccessToken() {
  var res = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({ app_id: FEISHU.appId, app_secret: FEISHU.appSecret }),
  });
  var data = await res.json();
  if (data.code !== 0) throw new Error("获取 token 失败: " + (data.msg || data.code));
  return data.tenant_access_token;
}

async function listAllRecords(token) {
  var records = [];
  var pageToken = null;
  while (true) {
    var res = await fetch(recordUrl(100, pageToken), {
      headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
    });
    var data = await res.json();
    if (data.code !== 0) throw new Error("查询记录失败: [" + data.code + "] " + data.msg);
    var items = data.data.items || [];
    records = records.concat(items);
    if (!data.data.has_more) break;
    pageToken = data.data.page_token;
  }
  return records;
}

function fieldValue(rec, name) {
  var val = (rec.fields || {})[name];
  if (val == null) return "";
  if (typeof val === "object" && val.link) return val.link;
  if (typeof val === "object" && val.text) return val.text;
  if (Array.isArray(val)) {
    return val.map(function (v) {
      return (v && typeof v === "object") ? (v.text || "") : String(v || "");
    }).join(", ");
  }
  return String(val);
}

// ── Data aggregation ──

// 「结果」列的分组。必须与 agent/status_rules.py 保持一致（改一处要三处同步：
// status_rules.py / 本文件 / 飞书列选项）。提醒状态列已改为公式列，不再参与统计。
var RESULT_REMINDABLE = ["简历", "测评", "面试"];                 // 进行中（还会被催）
var RESULT_LOST = ["简历挂", "一面挂", "二面挂", "三面挂"];         // 被拒
var RESULT_OFFER = ["offer"];
var RESULT_QUIET = ["无反馈", "放弃"];                            // 无结论结束
var RESULT_INTERVIEWED = ["面试", "一面挂", "二面挂", "三面挂", "offer"]; // 走到过面试的

function aggregate(records) {
  var total = records.length;
  var toApply = 0;
  var inProgress = 0;
  var interviewed = 0;
  var offered = 0;
  var lost = 0;
  var quiet = 0;

  var companyMap = {};
  var weekMap = {};

  records.forEach(function (rec) {
    var status = fieldValue(rec, "结果");
    var company = fieldValue(rec, "公司") || "未知";

    // 结果列只存"当前状态"，但它也是走得最远的状态，所以能推出漏斗
    if (status === "待投递") toApply++;
    else if (RESULT_OFFER.indexOf(status) >= 0) offered++;
    else if (RESULT_LOST.indexOf(status) >= 0) lost++;
    else if (RESULT_QUIET.indexOf(status) >= 0) quiet++;
    else if (RESULT_REMINDABLE.indexOf(status) >= 0) inProgress++;
    if (RESULT_INTERVIEWED.indexOf(status) >= 0) interviewed++;

    // Company aggregation
    companyMap[company] = (companyMap[company] || 0) + 1;

    // Week aggregation based on record creation time
    var created = rec.created_time || rec.created_at;
    if (created) {
      var d;
      try {
        d = new Date(created);
      } catch (e) {
        return;
      }
      // Get ISO week: Monday as first day
      var day = d.getDay() || 7; // Sunday = 0 → 7
      var monday = new Date(d);
      monday.setDate(d.getDate() - day + 1);
      monday.setHours(0, 0, 0, 0);
      var weekKey = monday.toISOString().slice(0, 10);
      weekMap[weekKey] = (weekMap[weekKey] || 0) + 1;
    }
  });

  // Sort companies by count desc, take top 10
  var companies = Object.entries(companyMap)
    .sort(function (a, b) { return b[1] - a[1]; })
    .slice(0, 10);

  // Sort weeks chronologically
  var weeks = Object.entries(weekMap)
    .sort(function (a, b) { return a[0] < b[0] ? -1 : 1; })
    .slice(-12); // last 12 weeks

  return {
    total: total,
    toApply: toApply,
    applied: total - toApply, // 真正投出去的（总投递里减去还没投的）
    inProgress: inProgress,
    interviewed: interviewed,
    offered: offered,
    lost: lost,
    quiet: quiet,
    companies: companies,
    weeks: weeks,
  };
}

// ── Chart rendering ──

function renderCharts(data) {
  // Funnel chart (bar chart showing pipeline stages)
  var funnelCtx = document.getElementById("funnelChart").getContext("2d");
  new Chart(funnelCtx, {
    type: "bar",
    data: {
      labels: ["总投递", "已投递", "进入面试", "offer"],
      datasets: [{
        label: "数量",
        data: [data.total, data.applied, data.interviewed, data.offered],
        backgroundColor: ["#3370ff", "#8e53d1", "#0d7a3e", "#d46b08"],
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, ticks: { stepSize: 1 } },
      },
    },
  });

  // Company distribution pie chart
  var companyCtx = document.getElementById("companyChart").getContext("2d");
  var colors = [
    "#3370ff", "#0d7a3e", "#d46b08", "#d83931", "#8e53d1",
    "#00a8a8", "#ff6b6b", "#4ecdc4", "#45b7d1", "#f9ca24",
  ];
  new Chart(companyCtx, {
    type: "doughnut",
    data: {
      labels: data.companies.map(function (c) { return c[0]; }),
      datasets: [{
        data: data.companies.map(function (c) { return c[1]; }),
        backgroundColor: colors.slice(0, data.companies.length),
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: {
          position: "bottom",
          labels: { font: { size: 11 }, padding: 12 },
        },
      },
    },
  });

  // Weekly timeline bar chart
  var timelineCtx = document.getElementById("timelineChart").getContext("2d");
  new Chart(timelineCtx, {
    type: "bar",
    data: {
      labels: data.weeks.map(function (w) { return w[0]; }),
      datasets: [{
        label: "投递数",
        data: data.weeks.map(function (w) { return w[1]; }),
        backgroundColor: "#3370ff",
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, ticks: { stepSize: 1 } },
      },
    },
  });
}

// ── Main ──

async function main() {
  try {
    // Load config from chrome.storage.local
    var cfgResult = await new Promise(function(resolve) {
      chrome.storage.local.get(['feishuConfig'], resolve);
    });
    var config = cfgResult.feishuConfig;
    if (!config || !config.appId || !config.appSecret || !config.appToken || !config.tableId) {
      document.getElementById('loading').style.display = 'none';
      document.getElementById('error').style.display = 'block';
      document.getElementById('error').textContent = '请先在插件弹窗中点击设置按钮，配置飞书账号';
      return;
    }
    FEISHU = config;

    var token = await getTenantAccessToken();
    var records = await listAllRecords(token);

    if (records.length === 0) {
      document.getElementById("loading").style.display = "none";
      document.getElementById("error").style.display = "block";
      document.getElementById("error").textContent = "表格中没有数据，先去投递几个岗位吧！";
      return;
    }

    var data = aggregate(records);

    // Update stats
    document.getElementById("statTotal").textContent = data.total;
    document.getElementById("statToApply").textContent = data.toApply;
    document.getElementById("statInProgress").textContent = data.inProgress;
    document.getElementById("statOffer").textContent = data.offered;
    document.getElementById("statLost").textContent = data.lost;

    renderCharts(data);

    document.getElementById("loading").style.display = "none";
    document.getElementById("content").style.display = "block";
    document.getElementById("refreshTime").textContent =
      "刷新于 " + new Date().toLocaleTimeString("zh-CN");
  } catch (e) {
    document.getElementById("loading").style.display = "none";
    document.getElementById("error").style.display = "block";
    document.getElementById("error").textContent = "数据加载失败: " + (e.message || e);
  }
}

document.addEventListener("DOMContentLoaded", main);
