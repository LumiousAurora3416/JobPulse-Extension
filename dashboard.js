/**
 * JobPulse 数据看板 — 从飞书多维表格拉取数据，用 Chart.js 渲染图表
 */

const FEISHU = {
  appId: "YOUR_APP_ID",
  appSecret: "YOUR_APP_SECRET",
  appToken: "YOUR_APP_TOKEN",
  tableId: "YOUR_TABLE_ID",
};

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

function aggregate(records) {
  var total = records.length;
  var interview = 0;
  var resumeSent = 0;
  var pending = 0;
  var followed = 0;
  var lost = 0;

  var companyMap = {};
  var weekMap = {};

  records.forEach(function (rec) {
    var status = fieldValue(rec, "结果");
    var remind = fieldValue(rec, "提醒状态");
    var company = fieldValue(rec, "公司") || "未知";

    if (status === "面试") interview++;
    if (status === "简历") resumeSent++;
    if (remind === "待跟进") pending++;
    if (remind === "已跟进") followed++;
    if (remind === "已失效" || remind === "简历挂") lost++;

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
    interview: interview,
    resumeSent: resumeSent,
    pending: pending,
    followed: followed,
    lost: lost,
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
      labels: ["总投递", "简历筛选", "进入面试"],
      datasets: [{
        label: "数量",
        data: [data.total, data.resumeSent, data.interview],
        backgroundColor: ["#3370ff", "#8eb5ff", "#0d7a3e"],
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
    document.getElementById("statInterview").textContent = data.interview;
    document.getElementById("statPending").textContent = data.pending;
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
