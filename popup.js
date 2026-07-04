/**
 * 飞书自建应用配置
 * 优先从 chrome.storage.local 读取（用户在 setup.html 中填入）
 */
let FEISHU = null;
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

  /** 提取「职责」和「要求」两块正文，支持多种章节标题变体 */
  function extractDescReqModules(fullText) {
    const t = clean(fullText);
    if (!t) return "";

    const endSection =
      /(?:福利待遇|薪资福利|工作地点|办公地址|公司介绍|关于我们|投递方式|相似职位|你可能感兴趣|相关推荐|查看更多|热招职位|职位列表|岗位亮点)/;

    // 职责类标题 —— 描述具体工作内容
    const dutyHeadings = [
      "职位描述", "岗位职责", "工作职责", "岗位描述",
      "职位介绍", "工作内容", "职责描述", "你需要做",
      "你将会负责", "工作范围", "岗位介绍",
    ];
    // 要求类标题 —— 描述任职条件
    const reqHeadings = [
      "职位要求", "任职要求", "任职资格", "岗位要求",
      "工作要求", "任职条件", "资格要求", "应聘条件",
      "招聘要求", "岗位需求", "职位需求",
    ];

    function findFirst(patterns, text) {
      let best = null;
      for (const p of patterns) {
        const idx = text.indexOf(p);
        if (idx >= 0 && (best === null || idx < best.index)) {
          best = { index: idx, heading: p, length: p.length };
        }
      }
      return best;
    }

    /** 截断尾部无关内容（福利、公司介绍等） */
    function cutTail(s) {
      if (!s) return "";
      const m = s.search(endSection);
      if (m >= 0) s = s.slice(0, m).trim();
      if (s.length > 45000) s = s.slice(0, 45000);
      return s;
    }

    /** 从匹配位置开始，跳过标题文本和其后可能的分隔符/空白 */
    function sliceAfter(match, text) {
      const raw = text.slice(match.index + match.length);
      const sep = raw.match(/^\s*[：:、\s]*/);
      return raw.slice(sep ? sep[0].length : 0).trim();
    }

    const duty = findFirst(dutyHeadings, t);
    const req = findFirst(reqHeadings, t);

    let bodyDesc = "";
    let bodyReq = "";

    if (duty && req) {
      if (req.index > duty.index) {
        // 正常顺序：职责在前，要求在后
        bodyDesc = t.slice(duty.index + duty.length, req.index).trim();
        bodyReq = sliceAfter(req, t);
      } else {
        // 少数网站顺序相反：要求在前，职责在后
        bodyReq = t.slice(req.index + req.length, duty.index).trim();
        bodyDesc = sliceAfter(duty, t);
      }
    } else if (duty) {
      // 只有职责标题，继续在后文中找要求标题
      const afterDuty = t.slice(duty.index + duty.length);
      const req2 = findFirst(reqHeadings, afterDuty);
      if (req2) {
        bodyDesc = afterDuty.slice(0, req2.index).trim();
        bodyReq = afterDuty.slice(req2.index + req2.length).trim();
      } else {
        bodyDesc = afterDuty.trim();
      }
    } else if (req) {
      bodyReq = sliceAfter(req, t);
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
    return /^(阿里巴巴校园招聘|阿里校招|校园招聘|社会招聘|首页|登录|官方招聘|招聘官网|加入我们|职位详情|职位搜索|岗位详情|网易招聘|美团招聘|热招职位|全部职位|Alibaba Campus Recruitment|Campus Recruitment|Jobs|Home|Filter by|Search Results)$/i.test(
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
  } else if (/kuaishou/.test(hostname) && !company) {
    company = "快手";
  } else if (/hr\.163\.com/.test(hostname) && !company) {
    company = "网易";
  } else if (/zhaopin\.meituan/.test(hostname) && !company) {
    company = "美团";
  } else if (/zhipin\.com/.test(hostname) && !company) {
    // BOSS直聘: company name is in a link with /company/ in href
    var zhipinCompany = document.querySelector('a[href*="/company/"]');
    if (!zhipinCompany) zhipinCompany = document.querySelector(".job-detail-company a");
    if (!zhipinCompany) zhipinCompany = document.querySelector(".company-info a");
    if (!zhipinCompany) zhipinCompany = document.querySelector("a.company-name");
    if (zhipinCompany) company = clean(zhipinCompany.textContent);
    // Fallback: parse page title format "{position}-{company}-BOSS直聘"
    if (!company) {
      var titleSegs = pageTitle.split(/[\-|–—|｜]/).map(clean).filter(Boolean);
      for (var ts = 0; ts < titleSegs.length; ts++) {
        var seg = titleSegs[ts];
        // Skip segments that look like position titles or "BOSS直聘"
        if (/BOSS|直聘|工程师|经理|专员|运营|设计|开发|产品|算法|测试|销售|市场|实习/i.test(seg)) continue;
        if (seg.length >= 2 && seg.length <= 20) { company = seg; break; }
      }
    }
    // Safety: never allow "BOSS直聘" as company name
    if (/BOSS直聘|boss/i.test(company)) company = "";
  } else if (/mokahr\.com/.test(hostname) && !company) {
    // mokahr: extract company slug from URL path
    // e.g. campus_apply/ruijie/136206 → "ruijie" → map to Chinese name
    const mokaMatch = location.pathname.match(/campus_apply\/([^/]+)/);
    if (mokaMatch) {
      const slugMap = {
        ruijie: "锐捷", xiaomi: "小米", bilibili: "哔哩哔哩",
        oppo: "OPPO", vivo: "vivo", lenovo: "联想",
        huawei: "华为", bytedance: "字节跳动", didi: "滴滴",
        jd: "京东", pdd: "拼多多", sf: "顺丰",
        bankcomm: "交通银行", cmb: "招商银行", icbc: "工商银行",
      };
      company = slugMap[mokaMatch[1]] || mokaMatch[1];
    }
  }

  if (!position || isBadTitle(position)) {
    const positionSelectors = [
      // BOSS直聘 zhipin.com
      "div.name > h1",
      "div.job-name > h1",
      ".job-title > h1",
      "div.job-detail-header h1",
      '[class*="job-detail"] h1',
      // 网易 hr.163.com
      '[class*="job-name"]',
      '[class*="job-detail-title"]',
      '[class*="position-title"]',
      // 美团 zhaopin.meituan.com
      '[class*="PositionName"]',
      '[class*="positionName"]',
      '[class*="job-title-text"]',
      '[class*="detail-title"]',
      // mokahr campus_apply
      '[class*="position-name"]',
      '[class*="campus-position"]',
      '[class*="campus-title"]',
      // Generic fallbacks
      '[class*="positionTitle"]',
      '[class*="PositionTitle"]',
      '[class*="jobTitle"]',
      '[class*="job-title"]',
      '[class*="JobTitle"]',
      '[class*="postTitle"]',
      '[class*="post-title"]',
      '[class*="name"][class*="position"]',
      '[class*="recruit-title"]',
      '[class*="title-name"]',
      // Extra: h1 inside detail containers
      '.job-detail h1',
      '.position-detail h1',
      '.position-detail h2',
      '.job-detail-content h1',
    ];
    for (const sel of positionSelectors) {
      const el = document.querySelector(sel);
      const tx = textFrom(el);
      if (tx && !isBadTitle(tx)) {
        position = tx;
        break;
      }
    }
  }

  if (!position || isBadTitle(position)) {
    // Split by common separators: -, |, –, —, ｜, _, ·, 「_」
    const segs = pageTitle.split(/[\-|–—|｜_·「」]/).map(clean).filter(Boolean);
    let bestPos = "";
    let bestScore = -1;
    for (const s of segs) {
      if (isBadTitle(s)) continue;
      let score = s.length;
      // Job title keywords boost score
      if (/工程师|经理|专员|运营|设计|开发|产品|算法|测试|销售|市场|实习|管培|顾问|分析师|技术员|架构|数据|架构师|负责人|总监|主管|组长|专家|研究员|策划|编辑|编导|翻译|审核|运维|安全|后端|前端|全栈|iOS|Android|iOS|SRE|DBA|QA|HR|BP|CFO|CTO|COO|VP|Head|Lead|Principal|Staff|Senior|Junior|Intern|Trainee|Engineer|Specialist|Assistant|Manager|Consultant|Analyst|Developer|Architect|Director|VP/i.test(s)) score += 30;
      if (score > bestScore) { bestScore = score; bestPos = s; }
    }
    if (bestPos) position = bestPos;
  }

  if (!position || isBadTitle(position)) {
    position = clean(pageTitle.split(/[-|–—|｜]/)[0]) || pageTitle;
  }

  if (!position || isBadTitle(position)) {
    for (const tag of ["h1", "h2"]) {
      const nodes = document.querySelectorAll(tag);
      for (const node of nodes) {
        const tx = textFrom(node);
        if (!tx || isBadTitle(tx)) continue;
        // 跳过招聘类别标签（如「日常实习」「暑期实习」等）
        if (/^(日常实习|暑期实习|寒假实习|周末实习|校园实习|提前批)$/.test(tx)) continue;
        // 短文本且无岗位关键词 → 大概率是公司名，暂存并继续找真正的岗位名
        if (tx.length <= 6 && !/工程师|经理|专员|运营|设计|开发|产品|算法|测试|销售|市场|实习|管培|顾问|分析师|技术员| intern|trainee|engineer|specialist|assistant|manager|consultant|analyst|developer/i.test(tx)) {
          if (!company) company = tx;
          continue;
        }
        position = tx;
        break;
      }
      if (position && !isBadTitle(position)) break;
    }
  }

  // 如果 position 来自 pageTitle 切分、company 仍为空，把前面的分段当作公司名
  if (!company && position && !isBadTitle(position)) {
    const segs = pageTitle.split(/[\-|–—|｜]/).map(clean).filter(Boolean);
    for (const seg of segs) {
      if (seg !== position && !isBadTitle(seg) && seg.length < 20 && !company) {
        // 职位名通常包含「实习生」「工程师」「经理」等关键词，公司名不含
        if (!/实习生|工程师|经理|专员|运营|设计|开发|实习|校招|社招|招聘|职位/i.test(seg)) {
          company = seg;
          break;
        }
      }
    }
  }

  // 最后清洗：如果已提取到公司名、但 position 看起来仍是公司名，清掉留给用户手动填
  if (position && company && !isBadTitle(position) && position.length <= 6 &&
      !/工程师|经理|专员|运营|设计|开发|产品|算法|测试|销售|市场|实习|管培|顾问|分析师|技术员/i.test(position)) {
    position = "";
  }

  if (!company) {
    const og = document.querySelector('meta[property="og:site_name"]');
    if (og && og.content) company = clean(og.content);
  }
  if (!company) {
    const companySelectors = [
      // 美团
      '[class*="CompanyName"]',
      '[class*="company-name"]',
      '[class*="companyName"]',
      '[class*="company_name"]',
      // mokahr
      '[class*="campus-company"]',
      '[class*="campus-company-name"]',
      // Generic fallbacks
      '[class*="recruit-company"]',
      '[class*="recruitCompany"]',
      '[class*="job-company"]',
      '[class*="jobCompany"]',
      '[class*="corporation-name"]',
      '[class*="organization-name"]',
    ];
    for (const sel of companySelectors) {
      const el = document.querySelector(sel);
      const tx = textFrom(el);
      if (tx && tx.length < 50) {
        company = tx;
        break;
      }
    }
  }

  /** CSS hidden text filter: remove interference text injected by sites like zhipin.com */
  function filterHiddenText(root) {
    var clone = root.cloneNode(true);
    var allEls = clone.querySelectorAll("*");
    for (var i = allEls.length - 1; i >= 0; i--) {
      var el = allEls[i];
      var cs = getComputedStyle(el);
      if (
        cs.display === "none" ||
        cs.visibility === "hidden" ||
        parseFloat(cs.opacity) === 0 ||
        parseFloat(cs.fontSize) === 0 ||
        (cs.width === "0px" && cs.height === "0px")
      ) {
        el.parentNode && el.parentNode.removeChild(el);
      }
    }
    return textFrom(clone);
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

  var posClean = clean(position);
  // 美团 zhaopin.meituan.com: if position is still garbage, try page title parsing
  var isMeituan = /zhaopin\.meituan/.test(hostname);
  if (isMeituan && (!posClean || isBadTitle(posClean))) {
    // 美团页面标题格式: "职位名 - 公司名 - 美团招聘" 或 "职位名 - 美团"
    var mtSegs = pageTitle.split(/[\-|–—|｜]/).map(clean).filter(Boolean);
    for (var ms = 0; ms < mtSegs.length; ms++) {
      var seg = mtSegs[ms];
      if (!isBadTitle(seg) && seg.length <= 40 &&
          !/美团|招聘|校园|社会/i.test(seg)) {
        position = seg;
        posClean = clean(position);
        break;
      }
    }
  }

  jd = clean(jd);
  if (posClean && jd.startsWith(posClean)) {
    jd = jd.slice(posClean.length).trim();
  }

  if (jd.length > 45000) jd = jd.slice(0, 45000);

  // BOSS直聘: apply CSS hidden text filter to remove interference text
  var isZhipin = /zhipin\.com/.test(hostname);
  if (isZhipin && jd) {
    var tmpDiv = document.createElement("div");
    tmpDiv.innerHTML = jd;
    jd = filterHiddenText(tmpDiv);
  }

  // Salary extraction (zhipin displays it prominently, try on all sites)
  var salary = "";
  var salarySelectors = [
    "span.salary",
    ".job-salary",
    "[class*='salary']",
    ".salary-text",
  ];
  for (var si = 0; si < salarySelectors.length; si++) {
    var salaryEl = document.querySelector(salarySelectors[si]);
    if (salaryEl) {
      salary = clean(salaryEl.textContent);
      break;
    }
  }
  // zhipin: also try from page title segments (e.g. "15k-25k")
  if (!salary && isZhipin) {
    var titleSegs = pageTitle.split(/[\-|–—|｜]/).map(clean).filter(Boolean);
    for (var ts = 0; ts < titleSegs.length; ts++) {
      if (/\d+k/i.test(titleSegs[ts]) || /\d+-\d+k/i.test(titleSegs[ts])) {
        salary = titleSegs[ts];
        break;
      }
    }
  }
  // Clean up: remove invisible/special unicode chars (garbled text from icon fonts, etc.)
  if (salary) {
    salary = salary.replace(/[^\x20-\x7E一-鿿＀-￯　-〿 -⁯ -¿]/g, "");
    salary = clean(salary);
  }

  return {
    position: posClean,
    company: clean(company),
    jd,
    pageTitle,
    salary: salary,
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
  const salaryEl = document.getElementById("salary");

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
    if (salaryEl) salaryEl.value = "";
    return;
  }

  urlEl.value = u;

  try {
    const data = await scrapeActiveTab(tab.id);
    positionEl.value = data.position || "";
    companyEl.value = data.company || "";
    jdEl.value = data.jd || "";
    if (salaryEl) salaryEl.value = data.salary || "";
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
    if (salaryEl) salaryEl.value = "";
  }
}

function setLoading(loading) {
  const btn = document.getElementById("submitBtn");
  btn.disabled = loading;
  btn.textContent = loading ? "提交中…" : "写入飞书";
}

/**
 * Load Feishu config from chrome.storage.local.
 * If not configured, show a prompt to open setup page.
 */
function loadConfig() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["feishuConfig"], function (result) {
      var cfg = result.feishuConfig;
      if (cfg && cfg.appId && cfg.appSecret && cfg.appToken && cfg.tableId) {
        FEISHU = cfg;
        resolve(true);
      } else {
        FEISHU = null;
        resolve(false);
      }
    });
  });
}

function openSetup() {
  chrome.tabs.create({ url: "setup.html" });
}

document.addEventListener("DOMContentLoaded", async function () {
  var hasConfig = await loadConfig();
  if (!hasConfig) {
    document.getElementById("mainView").style.display = "none";
    document.getElementById("setupPrompt").style.display = "block";
    document.getElementById("openSetupBtn").addEventListener("click", openSetup);
    return;
  }

  // Set dynamic quick links from config
  document.getElementById("feishuTableLink").href =
    "https://bytedance.feishu.cn/base/" + FEISHU.appToken + "?table=" + FEISHU.tableId;
  document.getElementById("feishuBotLink").href =
    "https://applink.feishu.cn/client/chat/open?appId=" + FEISHU.appId;
  document.getElementById("setupLink").addEventListener("click", function (e) {
    e.preventDefault();
    openSetup();
  });

  fillFromPage();

  document.getElementById("submitBtn").addEventListener("click", async function () {
    hideMessage();

    const position = document.getElementById("position").value.trim();
    const company = document.getElementById("company").value.trim();
    const jobDesc = document.getElementById("jobDesc").value.trim();
    const applyUrl = document.getElementById("applyUrl").value.trim();
    const result = document.getElementById("result").value;
    const salaryEl = document.getElementById("salary");
    const salary = salaryEl ? salaryEl.value.trim() : "";

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
    if (salary) fields["薪资"] = salary;

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
