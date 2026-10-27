import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "slot-text/style.css"
import "./index.css"
import App from "./App.tsx"
import { SignedOut } from "@/components/signed-out"
import { TooltipProvider } from "@/components/ui/tooltip"
import { signIn } from "@/lib/session"

void signIn().then((login) =>
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      {login ? (
        <SignedOut login={login} />
      ) : (
        <TooltipProvider>
          <App />
        </TooltipProvider>
      )}
    </StrictMode>
  )
)
