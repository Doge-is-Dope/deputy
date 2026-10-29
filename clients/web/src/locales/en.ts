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
    new: "New",
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
    restore: "Undo",
    projects: "Projects",
    recents: "Recents",
    newProject: "New project",
    newInProject: "New conversation in this project",
    viewAll: "View all",
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
    deleteProjectAsk: (project, count) =>
      count === 1
        ? `Delete ${project} and its conversation?`
        : `Delete ${project} and its ${count} conversations?`,
    resize: "Resize the sidebar",
    toggle: "Toggle the sidebar",
    expand: "Expand the sidebar",
  },

  chats: {
    title: "All chats",
    search: "Search chats",
    clear: "Clear search",
    none: "No matching chats",
    count: (count) => (count === 1 ? "1 chat" : `${count} chats`),
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
    liveView: "Live view",
    liveViewWith: (connection) => `Live view, ${connection}`,
    showLiveView: "Show the live view",
    showPlan: "Show the plan",
    hidePlan: "Hide the plan",
    hideLiveView: "Hide the live view",
    resizeLiveView: "Resize the live view",
    liveViewDescription: "Watch and take over the Windows desktop",
    openConversation: "Open",
    waitingApproval: "The agent needs your approval",
    replied: "The agent replied",
  },

  composer: {
    goal: "Task goal",
    stop: "Stop",
    stopTask: "Stop this task",
    start: "Start the task",
    send: "Send",
    withdraw: "Delete",
    mention: {
      list: "Mentions",
      computer: "Use the Windows computer",
    },
    handover: {
      title: "Hand the desktop to the agent?",
      keep: "Keep control",
      start: "Hand over and start",
    },
    approval: {
      ask: (consequence) => `Allow the agent to: ${consequence}?`,
      approve: "Allow",
      decline: "Decline",
      placeholder: "Or tell the agent what to do instead",
    },
    afterTask: "You can send once this task ends",
    takeover: {
      ask: (reason) => `The agent asks you to take over: ${reason}`,
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
    atCursor: "at the pointer",
    screenshot: "Take a screenshot",
    zoom: (region) => `Zoom in on ${region}`,
    drag: (from, to) => `Drag ${from} → ${to}`,
    move: (to) => `Move the pointer to ${to}`,
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
    code: {
      run: "Run a command",
      write: (path) => `Write ${path}`,
    },
    // What a group of steps did, each kind once: "Clicked, typed text, pressed keys".
    kinds: {
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
      worked: "Worked",
      failed: "Didn't finish",
      stopped: "Stopped",
      paused: "You're in control; the agent is paused",
      operated: (time) => `You had control for ${time}`,
      tookOver: "You took over the desktop",
      reconnecting: "Reconnecting to the desktop",
      wasOffline: (time) => `Desktop was disconnected for ${time}`,
      gaveUp: (time) => `The desktop didn't reconnect within ${time}`,
      waiting: {
        approval: "Waiting for your OK",
        takeover: "Waiting for you to take over",
        control: "You're in control",
        desktop: "Waiting for the desktop",
      },
      live: "Open the live view",
      details: "Show this step's details",
      full: "Show every step's screen",
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
    read: "Read",
    usage: "Usage",
    about: {
      cost: "Cost",
      took: "Time",
      unknown: "Unknown",
      details: "Usage details",
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
    agentAsks: "The agent asks you to take over",
    continued: "Continued from where it stopped",
    errors: {
      "E-DESKTOP":
        "Couldn't reach the desktop, so the agent could neither see nor use it.",
      "E-MODEL-KEY":
        "The model service didn't accept the API key. Ask your admin to check it.",
      "E-MODEL-LIMIT":
        "The model service's usage limit was reached. Try again later.",
      "E-MODEL-DOWN": "Couldn't reach the model service. Try again later.",
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
    expand: "Expand the live view",
    shrink: "Shrink the live view",
    exitFullscreen: "Exit full screen",
    close: "Close the live view",
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
    accountName: "Name",
    signInMethod: "Sign-in",
    signInNone: "None, this machine only",
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
    importTheme: "Import theme",
    importAction: "Import",
    themeText: "Theme text",
    themeImported: (mode: string) => `${mode} theme imported`,
    windowsDesktop: "Windows desktop",
    codeRunner: "Code runner",
    connected: "Connected",
    disconnected: "Not connected",
    connecting: "Connecting…",
    mainAgent: "Main agent",
    computerAgent: "Computer-use agent",
    codingAgent: "Coding agent",
    titleGeneration: "Title generation",
    effort: "Reasoning effort",
    byDefault: " (Default)",
    resetModels: "Reset",
    // The memory page: what the agent learned from the user's interventions (lib/memory.ts), and the two switches
    // Claude's own memory settings have, one for writing and one for reading.
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
