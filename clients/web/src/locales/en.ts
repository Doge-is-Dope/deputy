import type { Messages } from "@/locales/zh-Hant"

// The interface's words in English.

// Which way a scroll goes, as the phrase puts it.
const SCROLL: Record<string, string> = {
  up: "up ",
  down: "down ",
  left: "left ",
  right: "right ",
}

export const en: Messages = {
  common: {
    close: "Close",
    loading: "Loading",
    copy: "Copy",
    copyDetails: "Copy error details",
    copied: "Copied",
    cancel: "Cancel",
  },

  signedOut: {
    token: "Sign in needed",
    tokenHow:
      "Open this page with the sign-in link the runtime printed when it started.",
    proxy: "Couldn't confirm who you are",
    proxyHow: "Go back through your sign-in page.",
  },

  dates: {
    justNow: "just now",
  },
  duration: (minutes, seconds) =>
    minutes
      ? seconds
        ? `${minutes}m ${seconds}s`
        : `${minutes}m`
      : `${seconds}s`,
  durationHours: (hours, minutes) =>
    minutes ? `${hours}h ${minutes}m` : `${hours}h`,

  sidebar: {
    title: "Sidebar",
    description: "Tasks",
    new: "New chat",
    search: "Search",
    signOut: "Sign out",
    loadFailed: "Couldn't load conversations",
    running: "Running",
    needsAttention: "Needs you",
    unread: "New reply",
    failed: "Failed",
    more: "More",
    renameConversation: "Rename",
    deleteConversation: "Delete",
    project: "Project",
    removeFromProject: (project) => `Remove from ${project}`,
    deleted: "Conversation deleted",
    deletedProject: (project) => `Project ${project} deleted`,
    // The deleted notice's button, and the memory notice's (memory/notices.tsx).
    restore: "Undo",
    projects: "Projects",
    recents: "Recents",
    newProject: "New project",
    newInProject: "New conversation in this project",
    noChats: "No chats",
    showMore: "Show more",
    projectName: "Project name",
    create: "Create",
    newReplies: (count) =>
      count === 1 ? "1 new reply" : `${count} new replies`,
    renameProject: "Rename",
    // A project's menu: the rules the agent keeps for its conversations only, in a dialog titled with its name.
    projectMemory: "Memory",
    projectMemoryTitle: (project: string) => `Memory in ${project}`,
    deleteProject: "Delete",
    deleteProjectAsk: (project) =>
      `Delete ${project} and all its conversations?`,
    resize: "Resize the sidebar",
    toggle: "Toggle the sidebar",
    expand: "Expand the sidebar",
  },

  chats: {
    search: "Search",
    none: "No matches",
    // The search's sections.
    actions: "Quick actions",
    chats: "Chats",
  },

  home: {
    // The heading, by the time of day (greeting in format.ts).
    greeting: {
      morning: "Good morning. What can I help with?",
      afternoon: "Good afternoon. What can I help with?",
      evening: "Good evening. What can I help with?",
      night: "Up late? What can I help with?",
    },
    suggestions: [
      {
        label: "Polish a supplier reply",
        goal: 'Make this reply to a supplier more polite: "Your quote is too expensive. Can you lower the price?"',
      },
      {
        label: "Draw a rocket in Paint",
        goal: "Open Paint, draw a rocket blasting off, and save the picture to the desktop.",
      },
      {
        label: "Summarize a PDF and count primes",
        goal: "Open any PDF on the desktop and summarize it. Meanwhile, count the primes from 1 to 10,000 and add them up, then type both numbers into Notepad without saving.",
      },
    ],
    placeholderNew: "Ask anything",
    placeholderNext: "What next?",
    busy: "Another task is using the desktop",
    conversationBusy: "Still working on your last message",
    cantContinue: "Can't continue; start a new chat",
    deleted: "Conversation not found",
    offline: "Can't reach the service. Try again.",
    blockedOffline: "Can't reach the service right now",
    showPlan: "Show the plan",
    hidePlan: "Hide the plan",
    openConversation: "Open",
    waitingApproval: "The agent needs your approval",
    replied: "The agent replied",
  },

  composer: {
    goal: "Task goal",
    stop: "Stop",
    start: "Start the task",
    send: "Send",
    queue: "Queue",
    withdraw: "Delete",
    attachments: {
      add: "Add photos or files",
      remove: (name: string) => `Remove ${name}`,
      uploading: "Uploading",
      retry: "Upload again",
      open: (name: string) => `View ${name}`,
      more: (count: number) => `${count} more`,
      fold: "Show less",
      // Files dragged over the page.
      drop: "Drop to attach",
      dropHint: "Up to 5 files, each up to 20 MB",
      size: "A file can be at most 20 MB",
      // A file card's kind, for a name with no extension.
      file: "File",
      // An upload that failed: one that can go if tried again, and one that cannot be read at all.
      failed: (name: string) => `${name} didn't upload. Try again.`,
      unreadable: (name: string) => `Couldn't read ${name}`,
      many: (count: number) => `A message can have at most ${count} files`,
      folder: "Can't attach a folder. Zip it first.",
    },
    approval: {
      ask: (consequence) => `Allow the agent to: ${consequence}?`,
      approve: "Allow",
      decline: "Decline",
      placeholder: "Or tell the agent what to do instead",
    },
    takeover: {
      ask: (reason) => `The agent needs you to take over: ${reason}`,
      skip: "Skip",
      skipFailed: "Couldn't skip",
    },
  },

  connection: {
    offline: "Can't reach the service",
    offlineDetail: "Reconnecting…",
    reconnecting: "Connection lost, reconnecting…",
    connected: "Desktop connected",
    disconnected: "Desktop not connected",
  },

  actions: {
    clicks: {
      left_click: "Click",
      right_click: "Right-click",
      middle_click: "Middle-click",
      double_click: "Double-click",
      triple_click: "Triple-click",
    },
    screenshot: "Take a screenshot",
    zoom: "Zoom in",
    drag: "Drag",
    move: "Move the pointer",
    mouseDown: "Press the left button",
    mouseUp: "Release the left button",
    cursorPosition: "Find the pointer",
    scroll: (direction, amount) =>
      `Scroll ${SCROLL[direction] ?? ""}by ${amount}`,
    type: (text) => `Type “${text}”`,
    key: (keys, repeat) => `Press ${keys}${repeat}`,
    holdKey: (key, seconds) => `Hold ${key} for ${seconds}s`,
    wait: (seconds) => `Wait ${seconds}s`,
    requestTakeover: (reason) =>
      reason ? `Ask you to take over: ${reason}` : "Ask you to take over",
    plan: { read: "Read the plan", finished: "Finished a step" },
    code: {
      run: "Run a command",
      write: (path) => `Write ${path}`,
      view: (path) => `View ${path}`,
    },
    // What a group of steps did, each kind once: "Clicked, typed text, pressed keys".
    kinds: {
      plan: "read the plan",
      click: "clicked",
      drag: "dragged",
      move: "moved the pointer",
      look: "looked at the screen",
      type: "typed text",
      key: "pressed keys",
      scroll: "scrolled",
      wait: "waited",
      takeover: "asked you to take over",
      run: "ran commands",
      write: "wrote files",
      view: "looked at images",
    },
    kindList: (kinds: string[]) => {
      const list = kinds.join(", ")
      return list.charAt(0).toUpperCase() + list.slice(1)
    },
  },

  notes: {
    userControl: "You took over the desktop; the agent is paused.",
    controlReturned: (duration) =>
      `Control is back (you had it for ${duration}); the agent looks at the screen again and carries on.`,
    interrupted: (action) =>
      `The last run stopped during ${action}; whether that action happened is unknown.`,
    stuck: (actions) =>
      `Stopped: the last ${actions} actions didn't change the screen.`,
    gone: (duration) =>
      `Stopped: the desktop didn't reconnect within ${duration}.`,
    declined: (steps) => `Stopped: you declined ${steps} of its steps.`,
    unusable:
      "Stopped: couldn't reach the desktop, so the agent could neither see nor use it.",
    runnerUnusable: "Stopped: couldn't reach the code runner.",
  },

  run: {
    question: {
      recommended: "Recommended",
      typeBelow: "Reply in the message box.",
      placeholder: "Type your answer",
      pickMany: "Choose any",
      picked: (count: number) => `${count} selected`,
      list: (labels: string[]) => labels.join(", "),
      pressEnterMany: "Pick your answers and send, or type your own",
      pressEnter: "Pick an answer, or type your own",
    },
    // What the main agent remembered (under its reply) and the rules a task was given (in the task).
    memory: {
      remembered: "Remembered",
      updated: "Memory updated",
      rememberedMany: (count: number) => `Remembered ${count}`,
      deleted: (rule: string) => `Deleted: ${rule}`,
      following: (rule: string) => `Following: ${rule}`,
      citations: (count) =>
        count === 1 ? "1 memory citation" : `${count} memory citations`,
      cited: "Memories cited",
      failed: "Couldn't change memory. Try again.",
    },
    work: {
      working: "Working",
      failed: "Didn't finish",
      stopped: "Stopped",
      paused: "You're in control; the agent is paused",
      operated: (time) => `You had control for ${time}`,
      tookOver: "You took over the desktop",
      reconnecting: "Reconnecting to the desktop",
      wasOffline: (time) => `Desktop was disconnected for ${time}`,
      gaveUp: (time) => `The desktop didn't reconnect within ${time}`,
      waiting: {
        answer: "Waiting for an answer",
        approval: "Waiting for your OK",
        takeover: "Waiting for you to take over",
        control: "You're in control",
        desktop: "Waiting for the desktop",
      },
      live: "Open the live view",
    },
    agents: {
      working: (count: number) =>
        count === 1 ? "1 agent working" : `${count} agents working`,
      worked: (count: number) => `${count} agents worked`,
      done: (count: number) => `${count} done`,
    },
    thinking: "Thinking",
    plan: "Plan", // the steps the main agent listed for the work
    busy: {
      model: "Thinking about the next step",
    },
    skipped: {
      userControl: "Not run: you had control",
      userActed:
        "Not run: you just used the desktop, so the agent decides again from the new screen",
      screenChanged:
        "Not run: the screen changed, so the agent decides again from the new screen",
      disconnected: "Not run: the desktop is disconnected",
      declined: "Not run: you declined this step",
      tookControl: "Not run: you took this step over",
      batched: "Not run: a step that needs approval goes on its own",
      unexplained: "Not run: it didn't say what this step would do",
      desktopBusy: "Not run: another conversation is using the desktop",
      taskLimit: "Not run: the same work goes to the computer twice at most",
      computerInUse: "Not run: another task is using the computer",
      tooManyTasks: "Not run: six tasks are already running",
    },
    usage: "Usage",
    about: {
      cost: "Cost",
      took: "Time",
      unknown: "Unknown",
      details: "Usage details",
      total: "Total",
      input: "Input",
      cached: "Cache read",
      cacheWrite: "Cache write",
      output: "Output",
    },
    confirm: {
      approved: "You approved this step",
      autoApproved: (reason) =>
        reason
          ? `Auto review allowed this step: ${reason}`
          : "Auto review allowed this step",
      reviewing: "Auto review is checking this step",
      unanswered: "No answer, so this step didn't run",
    },
    enlarge: (label) => `Enlarge: ${label}`,
    agentAsks: "The agent needs you to take over",
    workedFor: (time) => `Worked for ${time}`,
    errors: {
      "E-DESKTOP":
        "Couldn't reach the desktop, so the agent could neither see nor use it.",
      "E-MODEL-KEY":
        "The model service didn't accept the API key. Ask your admin to check it.",
      "E-MODEL-LIMIT":
        "The model service's usage limit was reached. Try again later.",
      "E-MODEL-DOWN":
        "The model service is busy or having problems. Try again later.",
      "E-MODEL-REQUEST": "The model service turned down the request.",
      "E-CALL-LIMIT":
        "The agent called the model too many times without replying, so it was stopped.",
      "E-UNKNOWN": "Something unexpected went wrong.",
    },
    scrollToLatest: "Scroll to the latest",
    notFound: "Can't show this conversation",
    loadFailed: "Couldn't load this conversation",
  },

  screenshots: {
    previous: "Previous",
    next: "Next",
  },

  tabs: {
    title: "Tabs",
    description: "The computer's live view and attachment previews",
    show: "Show tabs",
    hide: "Hide tabs",
    resize: "Resize tabs",
    expand: "Expand tabs",
    shrink: "Shrink tabs",
    computer: "Computer",
    computerWith: (connection) => `Computer, ${connection}`,
    closeFile: (name) => `Close ${name}`,
    download: "Download",
    zoom: "Zoom",
    fit: "Zoom to fit",
    loadFailed: "Couldn't load this file",
    pageFailed: "Couldn't show this page",
    truncated: "Showing the first 256 KB",
  },

  markup: {
    start: "Mark up",
    pen: "Pen",
    shape: "Shapes",
    comment: "Comment",
    color: "Color",
    rect: "Rectangle",
    ellipse: "Ellipse",
    arrow: "Arrow",
    colors: {
      red: "Red",
      yellow: "Yellow",
      green: "Green",
      blue: "Blue",
      black: "Black",
    },
    undo: "Undo",
    redo: "Redo",
    add: "Add to chat",
    done: "Done",
    commentPlaceholder: "Add a comment…",
    saveComment: "Save",
    deleteComment: "Delete comment",
    commentNumber: (number) => `Comment ${number}`,
    discard: {
      title: "Discard markup?",
      body: "What you drew won't be kept.",
      confirm: "Discard",
    },
    busy: "Add it once this task is done",
    answerFirst: "Answer the agent first, then add it",
    failed: "Couldn't make the marked-up image",
    finishFirst:
      "This picture has markup that isn't applied: choose Done to keep it or Cancel to drop it",
  },

  liveView: {
    label: "Live view",
    keyboard: "Keyboard input for the desktop",
    clickToType: "Click the screen to type",
    takeOverFirst: "Take over to use it",
    takeoverFailed: "Couldn't take over",
    returnFailed: "Couldn't return control",
    unavailable: "The desktop is unavailable",
    recovering: "Reconnecting",
    stillDown: "Still not back? Send the error details to your admin.",
    exitFullscreen: "Exit full screen",
    holdFullscreen: "Hold for full screen",
    connecting: "Connecting…",
    agent: "Your agent has\u00a0",
    you: "You're in\u00a0",
    control: "control",
    takeOver: "Take over",
    takingOver: "Taking over…",
    returningControl: "Returning control…",
    returnControl: "Return control",
  },

  settings: {
    title: "Settings",
    pages: "Settings pages",
    general: "General",
    account: "Account",
    userId: "User ID",
    signInNone: "This machine only",
    signInToken: "Access token",
    signInProxy: "Sign-in proxy",
    appearance: "Appearance",
    desktop: "Desktop",
    model: "Model",
    language: "Language",
    autoLanguage: "Auto-detect",
    mode: "Mode",
    modes: { system: "System", light: "Light", dark: "Dark" },
    theme: "Theme",
    defaultTheme: "Default",
    accent: "Accent",
    background: "Background",
    foreground: "Foreground",
    windowsDesktop: "Windows desktop",
    codeRunner: "Code runner",
    windowsCommands: "Windows commands",
    runCommands: {
      label: "Let the agent run commands",
      description:
        "Often quicker and more reliable than clicking, for tasks such as searching files",
    },
    connected: "Connected",
    disconnected: "Not connected",
    connecting: "Connecting…",
    mainAgent: "Main agent",
    computerAgent: "Computer-use agent",
    codingAgent: "Coding agent",
    titleGeneration: "Title generation",
    effort: "Reasoning effort",
    byDefault: " (Default)",
    modelUnavailable: { no_api_key: "API key not set" },
    resetModels: "Reset",
    // The memory page: what the agent learned from the user's interventions (lib/memory.ts), and its two switches, one
    // for writing and one for reading.
    memory: "Memory",
    memoryModes: {
      learn: {
        label: "Learn from my corrections",
        description: "Save a rule when you correct, decline or take over",
      },
      use: {
        label: "Use memory",
        description: "Follow the rules you've taught",
      },
    },
    resetMemory: "Delete all memory",
    resetMemoryAsk: "Delete all memory?",
    resetMemoryDetail: "This can't be undone.",
    memoryEmpty: "Nothing remembered yet.",
    memoryLoadFailed: "Couldn't load memory.",
    memoryRule: "Rule",
    memoryWhy: "Why",
    memoryApplies: "Applies to",
    memoryFrom: "From",
    memorySource: "Conversation",
    editMemory: "Edit",
    memoryDeleted: "Memory deleted",
    deleteMemory: "Delete",
    saveMemory: "Save",
    permissions: "Permissions",
    approvals: "Approvals",
    approvalModes: {
      ask: {
        label: "Ask me every time",
        description: "Every risky action waits for approval",
      },
      auto: {
        label: "Auto review",
        description: "AI reviews risky actions and asks only when needed",
      },
    },
  },
}
