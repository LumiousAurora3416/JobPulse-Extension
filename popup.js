/**
 * 飞书自建应用配置（勿将含 App Secret 的构建产物公开分发；生产环境建议走服务端代理）
 */
const FEISHU = {
  appId: "YOUR_APP_ID",
  appSecret: "YOUR_APP_SECRET",
  appToken: "YOUR_APP_TOKEN",
  tableId: "YOUR_TABLE_ID",
};

const TOKEN_URL =
  "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal";

function recordUrl() {
  return `https://open.feishu.cn/open-apis/bitable/v1/apps/${FEISHU.appToken}/tables/${FEISHU.tableId}/records`;
}

function showMessage(text, ok) {
  const el = document.getElementById("message");
  el.textContent = text;
  el.className = "msg show " + (ok ? "ok" : "err");
}

function hideMessage() {
  const el = document.getElementById("message");
  el.className = "msg";
  el.textContent = "";
}

const FEISHU_PERM_HINT =
  "请检查：① 飞书开放平台 → 应用 → 权限管理 → 开通「多维表格」等相关权限并发布版本；② 打开该多维表格 → 右上角「…」→ 添加文档应用 / 为自建应用授权访问此 Base；③ 若启用了 IP 白名单，将当前网络 IP 加入。";

async function readFeishuJson(res, actionLabel) {
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    const snippet = (text || "").trim().slice(0, 280);
    if (res.status === 403 || /forbidden/i.test(snippet)) {
      throw new Error(
        `飞书返回 403 Forbidden（${actionLabel}）。${FEISHU_PERM_HINT}`
      );
    }
    throw new Error(
      `${actionLabel} 响应异常 HTTP ${res.status}：${snippet || res.statusText}`
    );
  }
  if (!res.ok && (data.code === undefined || data.code === null)) {
    throw new Error(
      `${actionLabel} HTTP ${res.status}：${data.msg || text.slice(0, 200)}`
    );
  }
  return data;
}

async function getTenantAccessToken() {
  const res = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({
      app_id: FEISHU.appId,
      app_secret: FEISHU.appSecret,
    }),
  });
  const data = await readFeishuJson(res, "获取 tenant_access_token");
  if (data.code !== 0) {
    throw new Error(
      `[${data.code}] ${data.msg || "获取 token 失败"}。请核对 App ID / App Secret 是否正确。`
    );
  }
  return data.tenant_access_token;
}

/**
 * 字段名需与多维表格一致：岗位、公司、岗位JD、投递链接、结果
 */
async function createBitableRecord(token, fields) {
  const res = await fetch(recordUrl(), {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json; charset=utf-8",
    },
    body: JSON.stringify({ fields }),
  });
  const data = await readFeishuJson(res, "写入多维表格记录");
  if (data.code !== 0) {
    const code = data.code;
    const msg = data.msg || "";
    let hint = "";
    if (code === 99991663 || /permission|forbidden|无权|无权限/i.test(msg)) {
      hint = " " + FEISHU_PERM_HINT;
    } else if (code === 1254045 || /field|字段/i.test(msg)) {
      hint =
        " 请确认多维表格中字段名与类型一致（岗位、公司、岗位JD、投递链接、结果）。";
    }
    throw new Error(`[${code}] ${msg || "写入失败"}${hint}`);
  }
  return data;
}

/**
 * 在页面上下文中执行：解析岗位名、公司、JD（不依赖闭包，供 executeScript 序列化）
 */
function extractJobPageData() {
  function clean(s) {
    return String(s || "")
      .replace(/\u00a0/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function textFrom(el) {
    if (!el) return "";
    return clean(el.innerText || el.textContent || "");
  }

  function stripHtml(html) {
    const d = document.createElement("div");
    d.innerHTML = html;
    return textFrom(d);
  }

  /** 只保留「职位描述」「职位要求」两块正文（按页面中出现的顺序截取） */
  function extractDescReqModules(fullText) {
    const t = clean(fullText);
    if (!t) return "";

    const endSection =
      /(?:福利待遇|薪资福利|工作地点|办公地址|公司介绍|关于我们|投递方式|相似职位|你可能感兴趣|相关推荐|查看更多|热招职位|职位列表)/;

    const iDesc = t.indexOf("职位描述");
    const iReq = t.indexOf("职位要求");

    let bodyDesc = "";
    let bodyReq = "";

    if (iDesc >= 0 && iReq >= 0 && iReq > iDesc) {
      const headD = t.slice(iDesc);
      const mD = headD.match(/^职位描述\s*/);
      const startD = iDesc + (mD ? mD[0].length : 4);
      bodyDesc = t.slice(startD, iReq).trim();
      const headR = t.slice(iReq);
      const mR = headR.match(/^职位要求\s*/);
      const startR = iReq + (mR ? mR[0].length : 4);
      bodyReq = t.slice(startR).trim();
    } else if (iDesc >= 0) {
      const headD = t.slice(iDesc);
      const mD = headD.match(/^职位描述\s*/);
      const startD = iDesc + (mD ? mD[0].length : 4);
      const rest = t.slice(startD);
      const ir2 = rest.indexOf("职位要求");
      if (ir2 >= 0) {
        bodyDesc = rest.slice(0, ir2).trim();
        const tail = rest.slice(ir2);
        const mR = tail.match(/^职位要求\s*/);
        bodyReq = tail.slice(mR ? mR[0].length : 4).trim();
      } else {
        bodyDesc = rest.trim();
      }
    } else if (iReq >= 0) {
      const headR = t.slice(iReq);
      const mR = headR.match(/^职位要求\s*/);
      bodyReq = t.slice(iReq + (mR ? mR[0].length : 4)).trim();
    }

    function cutTail(s) {
      if (!s) return "";
      let x = s;
      const m = x.search(endSection);
      if (m >= 0) x = x.slice(0, m).trim();
      if (x.length > 45000) x = x.slice(0, 45000);
      return x;
    }

    bodyDesc = cutTail(bodyDesc);
    bodyReq = cutTail(bodyReq);

    const parts = [];
    if (bodyDesc) parts.push("【职位描述】\n" + bodyDesc);
    if (bodyReq) parts.push("【职位要求】\n" + bodyReq);
    return parts.join("\n\n");
  }

  function isBadTitle(t) {
    const s = clean(t);
    if (!s || s.length > 120) return true;
    return /^(阿里巴巴校园招聘|阿里校招|校园招聘|社会招聘|首页|登录|官方招聘|招聘官网|加入我们|职位详情|Alibaba Campus Recruitment|Campus Recruitment|Jobs|Home|Filter by)$/i.test(
      s
    );
  }

  const hostname = location.hostname || "";
  const pageTitle = document.title || "";

  let position = "";
  let company = "";
  let jd = "";
  let jsonLdDescription = "";

  try {
    document.querySelectorAll('script[type="application/ld+json"]').forEach((script) => {
      let data;
      try {
        data = JSON.parse(script.textContent.trim());
      } catch (e) {
        return;
      }
      const list = Array.isArray(data)
        ? data
        : data["@graph"]
          ? data["@graph"]
          : [data];
      for (const item of list) {
        if (!item || typeof item !== "object") continue;
        const types = item["@type"];
        const tArr = Array.isArray(types) ? types : types ? [types] : [];
        const isJob =
          tArr.some((x) => String(x).includes("JobPosting")) ||
          item["@type"] === "JobPosting";
        if (!isJob) continue;
        if (item.title && !position) position = clean(item.title);
        if (item.hiringOrganization) {
          const org = item.hiringOrganization;
          const name = typeof org === "string" ? org : org.name;
          if (name && !company) company = clean(name);
        }
        if (item.description && !jsonLdDescription) {
          jsonLdDescription = stripHtml(String(item.description));
        }
      }
    });
  } catch (e) {}

  if (/alibaba|campus-talent/.test(hostname) && !company) {
    company = "阿里巴巴";
  } else if (/tencent\.com/.test(hostname) && !company) {
    company = "腾讯";
  } else if (/bytedance|jobs\.feishu|larkjobs/.test(hostname) && !company) {
    company = "字节跳动";
  }

  if (/alibaba|campus-talent/.test(hostname) && (!position || isBadTitle(position))) {
    const selectors = [
      '[class*="positionTitle"]',
      '[class*="position-title"]',
      '[class*="PositionTitle"]',
      '[class*="jobTitle"]',
      '[class*="job-title"]',
      '[class*="JobTitle"]',
      '[class*="postTitle"]',
      '[class*="post-title"]',
      '[class*="name"][class*="position"]',
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      const tx = textFrom(el);
      if (tx && !isBadTitle(tx)) {
        position = tx;
        break;
      }
    }
  }

  if (!position || isBadTitle(position)) {
    for (const tag of ["h1", "h2"]) {
      const nodes = document.querySelectorAll(tag);
      for (const node of nodes) {
        const tx = textFrom(node);
        if (tx && !isBadTitle(tx)) {
          position = tx;
          break;
        }
      }
      if (position && !isBadTitle(position)) break;
    }
  }

  if (!position || isBadTitle(position)) {
    const segs = pageTitle.split(/[\-|–—|｜]/).map(clean).filter(Boolean);
    for (const seg of segs) {
      if (!isBadTitle(seg)) {
        position = seg;
        break;
      }
    }
  }

  if (!position || isBadTitle(position)) {
    position = clean(pageTitle.split(/[-|–—|｜]/)[0]) || pageTitle;
  }

  if (!company) {
    const og = document.querySelector('meta[property="og:site_name"]');
    if (og && og.content) company = clean(og.content);
  }

  function collectDetailText() {
    const jdSelectors = [
      '[class*="job-detail"]',
      '[class*="JobDetail"]',
      '[class*="position-detail"]',
      '[class*="PositionDetail"]',
      '[class*="jobDetail"]',
      '[class*="jd-content"]',
      '[class*="detail-content"]',
      '[class*="description"][class*="job"]',
      "article",
      "main",
      '[role="main"]',
    ];
    let best = "";
    for (const q of jdSelectors) {
      const el = document.querySelector(q);
      if (!el) continue;
      const clone = el.cloneNode(true);
      clone
        .querySelectorAll("nav, header, footer, script, style, noscript, iframe")
        .forEach((n) => n.remove());
      const t = textFrom(clone);
      if (t.length > best.length) best = t;
    }
    if (best.length < 80) {
      const main =
        document.querySelector("main") ||
        document.querySelector('[role="main"]') ||
        document.body;
      if (main) {
        const clone = main.cloneNode(true);
        clone
          .querySelectorAll("nav, header, footer, script, style, noscript, iframe")
          .forEach((n) => n.remove());
        best = textFrom(clone);
      }
    }
    return best;
  }

  const detailText = collectDetailText();
  jd = extractDescReqModules(detailText);
  if (!jd && jsonLdDescription) {
    jd = extractDescReqModules(jsonLdDescription);
  }
  if (!jd) {
    jd = extractDescReqModules(textFrom(document.body));
  }

  const posClean = clean(position);
  jd = clean(jd);
  if (posClean && jd.startsWith(posClean)) {
    jd = jd.slice(posClean.length).trim();
  }

  if (jd.length > 45000) jd = jd.slice(0, 45000);

  return {
    position: posClean,
    company: clean(company),
    jd,
    pageTitle,
  };
}

async function scrapeActiveTab(tabId) {
  const results = await chrome.scripting.executeScript({
    target: { tabId, allFrames: false },
    func: extractJobPageData,
  });
  const first = results && results[0];
  if (!first) throw new Error("未返回解析结果");
  if (first.error) {
    throw new Error(first.error.message || "页面脚本执行失败");
  }
  return first.result;
}

async function fillFromPage() {
  const positionEl = document.getElementById("position");
  const companyEl = document.getElementById("company");
  const urlEl = document.getElementById("applyUrl");
  const jdEl = document.getElementById("jobDesc");

  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs && tabs[0];
  if (!tab || tab.id == null) {
    positionEl.placeholder = "无法读取标签页";
    return;
  }

  const u = tab.url || "";
  if (
    !u ||
    u.startsWith("chrome://") ||
    u.startsWith("edge://") ||
    u.startsWith("about:") ||
    u.startsWith("chrome-extension://")
  ) {
    showMessage(
      "当前页面无法注入解析脚本（请在普通网页职位详情页打开）",
      false
    );
    positionEl.value = tab.title || "";
    companyEl.value = "";
    jdEl.value = "";
    urlEl.value = "";
    return;
  }

  urlEl.value = u;

  try {
    const data = await scrapeActiveTab(tab.id);
    positionEl.value = data.position || "";
    companyEl.value = data.company || "";
    jdEl.value = data.jd || "";
    hideMessage();
    if (
      !data.position ||
      /校园招聘|Campus Recruitment/i.test(data.position)
    ) {
      showMessage(
        "未识别到明确职位名：请在「岗位」中手动改为页面顶部职位（如产品实习生）。职位列表页信息较少，建议进入职位详情页再同步。",
        false
      );
    }
  } catch (e) {
    showMessage(
      "页面解析失败，可手动填写：" + (e.message || String(e)),
      false
    );
    positionEl.value = tab.title || "";
    companyEl.value = "";
    jdEl.value = "";
  }
}

function setLoading(loading) {
  const btn = document.getElementById("submitBtn");
  btn.disabled = loading;
  btn.textContent = loading ? "提交中…" : "写入飞书";
}

document.addEventListener("DOMContentLoaded", () => {
  fillFromPage();

  document.getElementById("submitBtn").addEventListener("click", async () => {
    hideMessage();

    const position = document.getElementById("position").value.trim();
    const company = document.getElementById("company").value.trim();
    const jobDesc = document.getElementById("jobDesc").value.trim();
    const applyUrl = document.getElementById("applyUrl").value.trim();
    const result = document.getElementById("result").value;

    if (!position) {
      showMessage("请填写岗位名称", false);
      return;
    }
    if (!company) {
      showMessage("请填写公司名称", false);
      return;
    }
    if (!applyUrl) {
      showMessage("投递链接无效，请在可访问的职位页打开本插件", false);
      return;
    }

    const fields = {
      岗位: position,
      公司: company,
      岗位JD: jobDesc,
      投递链接: {
        link: applyUrl,
        text: position || "投递链接",
      },
      结果: result,
    };

    setLoading(true);
    try {
      const token = await getTenantAccessToken();
      await createBitableRecord(token, fields);
      showMessage("已同步到飞书多维表格", true);
    } catch (e) {
      showMessage(e.message || String(e), false);
    } finally {
      setLoading(false);
    }
  });
});
