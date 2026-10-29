// The interface's words in Traditional Chinese, the language it was written in. Every other language has the same
// shape (Messages), so one missing a word fails to compile.

import type { ErrorCode } from "@/lib/api"

// Which way a scroll goes, as the phrase puts it.
const SCROLL: Record<string, string> = {
  up: "向上",
  down: "向下",
  left: "向左",
  right: "向右",
}

export const zhHant = {
  common: {
    close: "關閉",
    loading: "載入中",
    copy: "複製",
    copyDetails: "複製錯誤資訊",
    copied: "已複製",
    cancel: "取消",
  },

  signedOut: {
    token: "需要登入",
    tokenHow: "請用 runtime 啟動時印出的登入連結開啟這個頁面。",
    proxy: "無法確認你的身分",
    proxyHow: "請從登入頁重新進入。",
  },

  dates: {
    justNow: "剛剛", // under a minute ago; longer ago is said by Intl.RelativeTimeFormat
  },
  // A whole minute or hour without its zero: "1 分", not "1 分 0 秒".
  duration: (minutes: number, seconds: number) =>
    minutes
      ? seconds
        ? `${minutes} 分 ${seconds} 秒`
        : `${minutes} 分`
      : `${seconds} 秒`,
  // An hour or more: to the minute.
  durationHours: (hours: number, minutes: number) =>
    minutes ? `${hours} 小時 ${minutes} 分` : `${hours} 小時`,

  sidebar: {
    title: "側欄",
    description: "任務清單",
    new: "新增",
    search: "搜尋",
    signOut: "登出",
    loadFailed: "無法載入對話紀錄",
    running: "執行中",
    needsAttention: "需要你處理",
    // A conversation's latest run ended while the user was elsewhere: with a reply, or in an error.
    unread: "有新回覆",
    failed: "發生錯誤",
    more: "更多",
    renameConversation: "重新命名",
    deleteConversation: "刪除",
    project: "Project",
    removeFromProject: (project: string) => `從 ${project} 移除`,
    // The notice once deleted (into the runtime's trash), whose button brings it back.
    deleted: "已刪除對話",
    deletedProject: (project: string) => `Project ${project} 已刪除`,
    restore: "還原",
    // The sidebar's sections.
    projects: "Projects",
    recents: "Recents",
    newProject: "新增 Project",
    newInProject: "在這個 Project 新增對話",
    // Under the recents, to the page of every conversation; muted and to the left, as a project's Show more.
    viewAll: "查看全部",
    noChats: "尚無對話",
    // Under a project's first five conversations, for five more, as ChatGPT's projects list theirs.
    showMore: "顯示更多",
    projectName: "Project 名稱",
    create: "建立",
    // A project's row while folded: how many of its conversations ended since the user saw them.
    newReplies: (count: number) => `${count} 則新回覆`,
    renameProject: "重新命名",
    // A project's menu: the rules the agent keeps for its conversations only, in a dialog titled with its name.
    projectMemory: "記憶",
    projectMemoryTitle: (project: string) => `${project} 的記憶`,
    deleteProject: "刪除",
    deleteProjectAsk: (project: string, count: number) =>
      `刪除 ${project} 與 ${count} 段對話？`,
    resize: "調整側欄寬度",
    toggle: "切換側欄",
    expand: "展開側欄",
  },

  // The page of every conversation (chats-page.tsx).
  chats: {
    title: "所有對話",
    search: "搜尋對話",
    clear: "清除搜尋",
    none: "沒有符合的對話",
    count: (count: number) => `${count} 段對話`,
  },

  home: {
    // The heading, by the time of day (greeting in format.ts).
    greeting: {
      morning: "早安，有什麼可以幫你的？",
      afternoon: "午安，有什麼可以幫你的？",
      evening: "晚安，有什麼可以幫你的？",
      night: "夜深了，有什麼可以幫你的？",
    },
    // Self-contained tasks for a direct reply, Windows desktop work, and desktop work with code running beside it.
    suggestions: [
      {
        label: "潤飾供應商回覆",
        goal: "幫我把這句給供應商的回覆改得有禮貌一點：「報價太高了，能不能便宜一點？」",
      },
      {
        label: "用小畫家畫火箭",
        goal: "打開小畫家，畫一個正在升空的火箭，把圖片存到桌面。",
      },
      {
        label: "摘要 PDF 並算質數",
        goal: "打開桌面上任一個 PDF，幫我摘要重點；同時算出 1 到 10000 有幾個質數、全部加起來是多少，再把這兩個數字填進記事本，不要存檔。",
      },
    ],
    placeholderNew: "問任何問題",
    placeholderNext: "接著要做什麼？",
    // A message turned away: another conversation's task has the desktop, or this conversation is still on its last one.
    busy: "桌面正在跑另一個任務",
    conversationBusy: "這段對話還在處理上一則",
    cantContinue: "這段對話無法接續，請開新對話",
    deleted: "找不到這段對話",
    offline: "連不到服務，請稍後再試",
    blockedOffline: "暫時連不到服務",
    liveView: "即時畫面",
    liveViewWith: (connection: string) => `即時畫面，${connection}`,
    showLiveView: "顯示即時畫面",
    showPlan: "顯示計畫",
    hidePlan: "隱藏計畫",
    hideLiveView: "隱藏即時畫面",
    resizeLiveView: "調整即時畫面寬度",
    liveViewDescription: "Windows 桌面的即時畫面與接管",
    // On the notice that another conversation waits for the user.
    openConversation: "前往對話",
    waitingApproval: "Agent 等你確認",
    // Another conversation's run has ended: its answer, or a question for the user, is there.
    replied: "Agent 回覆了",
  },

  composer: {
    goal: "任務目標",
    stop: "停止",
    stopTask: "停止這個任務",
    start: "開始任務",
    // Sends what is written to the run in progress.
    send: "送出",
    // Takes back a message waiting above the composer, before the agent reads it.
    withdraw: "刪除",
    // The list typing @ opens: what a message can be sent to. Their names stay in English in every language, as the
    // runtime looks for them.
    mention: {
      list: "提及",
      computer: "操作 Windows 電腦",
    },
    // Asked before a task takes the desktop from the user who is using it.
    handover: {
      title: "讓 Agent 接管桌面？",
      keep: "保留控制權",
      start: "交給 Agent 並開始",
    },
    // A step the agent waits for the user to approve; what they write meanwhile declines it, as the reason.
    approval: {
      ask: (consequence: string) => `允許 Agent：${consequence}？`,
      approve: "允許",
      decline: "拒絕",
      placeholder: "或告訴 Agent 改怎麼做",
      // Sends what is written as the reason to decline the step.
    },
    // On the stop button, as Enter is pressed while a run from the command line works: it takes no message until it
    // ends.
    afterTask: "任務結束後就能送出",
    // The agent asking the user to take over, for something only they can do (a password, a code); skipping hands the
    // desktop straight back, for it to carry on without.
    takeover: {
      ask: (reason: string) => `Agent 請你接管：${reason}`,
      skip: "略過",
      skipFailed: "沒有略過成功",
    },
  },

  connection: {
    offline: "連不到服務",
    offlineDetail: "正在自動重新連線…",
    // A connection that dropped and is being made again: the conversation's events, or the live view's video.
    reconnecting: "連線中斷，重新連線中…",
    connected: "桌面已連線",
    disconnected: "桌面未連線",
  },

  actions: {
    clicks: {
      left_click: "點擊",
      right_click: "右鍵點擊",
      middle_click: "中鍵點擊",
      double_click: "雙擊",
      triple_click: "三連擊",
    } as Record<string, string>,
    atCursor: "游標位置",
    screenshot: "截圖",
    zoom: (region: string) => `放大檢視 ${region}`,
    drag: (from: string, to: string) => `拖曳 ${from} → ${to}`,
    move: (to: string) => `移動游標到 ${to}`,
    mouseDown: "按住左鍵",
    mouseUp: "放開左鍵",
    cursorPosition: "查詢游標位置",
    scroll: (direction: string, amount: unknown) =>
      `${SCROLL[direction] ?? ""}捲動 ${amount} 格`,
    type: (text: string) => `輸入「${text}」`,
    key: (keys: unknown, repeat: string) => `按 ${keys}${repeat}`,
    holdKey: (key: unknown, seconds: unknown) => `按住 ${key} ${seconds} 秒`,
    wait: (seconds: unknown) => `等待 ${seconds} 秒`,
    requestTakeover: (reason: string) =>
      reason ? `請你接管：${reason}` : "請你接管",
    code: {
      run: "執行指令",
      write: (path: string) => `寫入 ${path}`,
    },
    // What a group of steps did, each kind once: "點擊、輸入文字、按鍵".
    kinds: {
      click: "點擊",
      drag: "拖曳",
      move: "移動游標",
      look: "查看畫面",
      type: "輸入文字",
      key: "按鍵",
      scroll: "捲動",
      wait: "等待",
      takeover: "請你接管",
      run: "執行指令",
      write: "寫入檔案",
    },
    kindList: (kinds: string[]) => kinds.join("、"),
  },

  // What the runtime notes in a run's log (in English, for the log), as the conversation tells it.
  notes: {
    userControl: "你接管了桌面，agent 暫停中。",
    // A duration as formatDuration writes it: "1 分 15 秒".
    controlReturned: (duration: string) =>
      `控制權已交還（你操作了 ${duration}），agent 重新看畫面後繼續。`,
    interrupted: (action: string) =>
      `上一輪停在 ${action} 執行中，這個動作有沒有完成不確定。`,
    stuck: (actions: string) =>
      `已停止：最近 ${actions} 個動作都沒有改變畫面。`,
    gone: (duration: string) => `已停止：桌面 ${duration}內沒有重新連上。`,
    declined: (steps: string) => `已停止：你拒絕了 ${steps} 個步驟。`,
    unusable: "已停止：連不到桌面，看不到畫面也無法操作。",
    runnerUnusable: "已停止：連不到程式執行環境。",
  },

  run: {
    // What the main agent remembered (under its reply) and the rules a task was given (in the task).
    memory: {
      remembered: "已記住",
      updated: "已更新記憶",
      rememberedMany: (count: number) => `已記住 ${count} 條`,
      deleted: (rule: string) => `已刪除：${rule}`,
      following: (rule: string) => `遵守：${rule}`,
      // The run's last reply's details menu: the rules its tasks were handed over with, listed in a dialog.
      citations: (count: number) => `${count} 則記憶引用`,
      cited: "引用的記憶",
      failed: "無法變更記憶，請再試一次",
    },
    // Work handed over, as one group: how long it has worked, and how it stands.
    work: {
      working: "正在工作",
      worked: "已工作",
      failed: "沒有完成",
      stopped: "已停止",
      // The user has the desktop, the agent waiting for it; once it is back, how long they had it.
      paused: "你控制中，agent 已暫停",
      operated: (time: string) => `你操作了 ${time}`,
      tookOver: "你接管了桌面",
      // The desktop gone, the agent waiting for it to reconnect; once it is back, how long it was gone; or that it
      // gave up waiting.
      reconnecting: "正在重新連線桌面",
      wasOffline: (time: string) => `桌面斷線了 ${time}`,
      gaveUp: (time: string) => `桌面 ${time}內沒有重新連上`,
      // The summary of a task under way that waits, in place of "working".
      waiting: {
        approval: "等你確認",
        takeover: "等你接手",
        control: "你控制中",
        desktop: "等待桌面連線",
      },
      live: "打開即時畫面",
      details: "顯示這一步的細節",
      full: "顯示每一步的畫面",
    },
    // More than one agent at work at once: one line for them all, then a line per agent.
    agents: {
      working: (count: number) => `${count} 個 agent 正在工作`,
      worked: (count: number) => `${count} 個 agent 已工作`,
      done: (count: number) => `${count} 個完成`,
    },
    // The main agent working out what to say.
    thinking: "思考中",
    plan: "計畫", // the steps the main agent listed for the work
    busy: {
      model: "思考下一步",
    },
    // Actions the runtime held back on purpose: not failures, so said plainly and not in red.
    skipped: {
      userControl: "沒有執行：控制權在你手上",
      userActed: "沒有執行：你剛操作過桌面，agent 看新畫面重新判斷",
      screenChanged: "沒有執行：畫面已經變了，agent 看新畫面重新判斷",
      disconnected: "沒有執行：桌面沒有連線",
      declined: "沒有執行：你拒絕了這一步",
      tookControl: "沒有執行：你接管了桌面",
      batched: "沒有執行：需要確認的步驟要單獨送出",
      unexplained: "沒有執行：沒有說明這一步會做什麼",
      desktopBusy: "沒有執行：另一段對話正在使用桌面",
      // A third task for one step of the plan, or for one message without a plan (agent/main_agent.py).
      taskLimit: "沒有執行：同一件事最多交給電腦兩次",
      // A computer task handed over while another still used the computer (agent/main_agent.py).
      computerInUse: "沒有執行：另一件工作正在用電腦",
      // A task handed over while the most tasks at once already ran (agent/background.py).
      tooManyTasks: "沒有執行：已經有六件工作在進行",
    },
    // Under a message sent while the run worked, for a moment once an agent reads it.
    read: "已讀",
    // The details menu under a run's last reply: how long the run took and what it cost; an item opens a dialog of each
    // agent's model, and its tokens and cost of each kind.
    usage: "用量",
    about: {
      cost: "花費",
      took: "用時",
      unknown: "未知", // a model without a known price, or a call a stop cut off (agent/trajectory.py cut)
      details: "用量細節",
      input: "輸入",
      cached: "快取讀取",
      cacheWrite: "快取寫入",
      output: "輸出",
    },
    // A step the agent asks the user to approve before it is sent: the card, its choices and how it was answered.
    confirm: {
      approved: "你允許了這一步",
      // Auto review let it through (agent/review.py), with its reason, in the user's language.
      autoApproved: (reason: string) =>
        reason ? `自動審查允許了這一步：${reason}` : "自動審查允許了這一步",
      reviewing: "自動審查中",
      unanswered: "沒有回覆，這一步沒有執行",
    },
    enlarge: (label: string) => `放大：${label}`,
    agentAsks: "Agent 請你接管",
    continued: "從中斷處繼續",
    // Why a run failed (ErrorCode), said to whoever used it: what went wrong and what they can do. The code and the
    // technical detail go only into what they copy.
    errors: {
      "E-DESKTOP": "連不到桌面，Agent 看不到畫面，也無法操作。",
      "E-MODEL-KEY": "模型服務不接受目前的 API 金鑰，請管理員檢查。",
      "E-MODEL-LIMIT": "模型服務的用量已達上限，請稍後再試。",
      "E-MODEL-DOWN": "模型服務暫時連不上，請稍後再試。",
      "E-MODEL-REQUEST": "模型服務拒絕了這次的請求。",
      "E-CALL-LIMIT": "Agent 呼叫模型太多次還沒有回覆，已停止。",
      "E-UNKNOWN": "發生了預期外的錯誤。",
    } satisfies Record<ErrorCode, string>,
    scrollToLatest: "捲到最新",
    // A conversation that can't be shown: gone, or not loaded yet while the runtime can't be reached (it is tried again
    // on its own).
    notFound: "無法顯示這則對話",
    loadFailed: "無法載入這段對話",
  },

  screenshots: {
    previous: "上一張",
    next: "下一張",
  },

  liveView: {
    label: "即時畫面",
    keyboard: "桌面鍵盤輸入",
    clickToType: "點一下畫面就能用鍵盤輸入",
    takeOverFirst: "接管後才能操作",
    takeoverFailed: "沒有接管成功",
    returnFailed: "沒有交還成功",
    // Said to whoever uses the desktop, who can't fix it: what is wrong, that it is being fixed, and, if that lasts,
    // what to send to someone who can. The technical detail goes only into what they copy.
    unavailable: "桌面暫時無法使用",
    recovering: "正在自動重新連線",
    stillDown: "一直沒有恢復嗎？請把錯誤資訊傳給管理員。",
    expand: "放大即時畫面",
    shrink: "縮小即時畫面",
    exitFullscreen: "結束全螢幕",
    close: "關閉即時畫面",
    connecting: "連線中…",
    // Who has control, in two parts: the first rolls over when control changes hands, the rest stays. A space
    // between them goes at the end of the first, unbreakable, or the layout drops it.
    agent: "Agent\u00a0",
    you: "你",
    control: "控制中", // holding control, not operating: the agent holds it while nothing runs too
    takeOver: "接管",
    takingOver: "接管中…",
    returningControl: "交還中…",
    returnControl: "交還控制權",
  },

  settings: {
    title: "設定",
    pages: "設定頁面",
    general: "一般",
    account: "帳號",
    accountName: "名稱",
    signInMethod: "登入方式",
    signInNone: "不需登入，僅限本機",
    signInToken: "存取權杖",
    signInProxy: "登入服務",
    appearance: "外觀",
    desktop: "桌面",
    model: "模型",
    language: "語言",
    autoLanguage: "自動偵測",
    mode: "模式",
    modes: { system: "跟隨系統", light: "淺色", dark: "深色" },
    theme: "主題",
    defaultTheme: "預設",
    // A theme's three colors, named as the ChatGPT desktop app names them in its own Appearance settings.
    accent: "強調色",
    background: "背景",
    foreground: "前景",
    importTheme: "匯入主題",
    importAction: "匯入",
    themeText: "主題文字",
    themeImported: (mode: string) => `已匯入${mode}主題`,
    windowsDesktop: "Windows 桌面",
    codeRunner: "程式執行環境",
    connected: "已連線",
    disconnected: "未連線",
    connecting: "連線中…",
    mainAgent: "主 agent",
    computerAgent: "電腦 agent",
    codingAgent: "程式 agent",
    titleGeneration: "標題生成",
    effort: "推理強度",
    byDefault: "（預設）",
    resetModels: "重設",
    // The memory page: what the agent learned from the user's interventions (lib/memory.ts), and the two switches
    // Claude's own memory settings have, one for writing and one for reading.
    memory: "記憶",
    memoryModes: {
      learn: {
        label: "從我的糾正中學習",
        description: "你糾正、拒絕或接管時，記下規則",
      },
      use: {
        label: "使用記憶",
        description: "遵守記住的規則",
      },
    },
    resetMemory: "刪除全部記憶",
    resetMemoryAsk: "要刪除所有記憶嗎？",
    resetMemoryDetail: "無法復原。",
    memoryEmpty: "還沒有記憶。",
    memoryLoadFailed: "無法載入記憶。",
    memoryRule: "規則",
    memoryWhy: "原因",
    memoryApplies: "適用於",
    memoryFrom: "來源",
    memorySource: "對話",
    editMemory: "編輯",
    memoryDeleted: "已刪除記憶",
    deleteMemory: "刪除",
    saveMemory: "儲存",
    permissions: "權限",
    // How a step the agent flags for approval is answered (agent/review.py), each with one general line and no
    // examples, as Claude's permission modes say theirs. Both name the same steps, the risky ones the agent flags
    // (computer_agent.py), so the lines differ only in who decides.
    approvals: "執行前確認",
    approvalModes: {
      ask: {
        label: "每次問我",
        description: "有風險的操作全部先詢問",
      },
      auto: {
        label: "自動審查",
        description: "有風險的操作先由 AI 審查，必要時才詢問",
      },
    },
  },
}

export type Messages = typeof zhHant
