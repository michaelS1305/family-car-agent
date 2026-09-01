import { useState } from 'react'
import type { InternalUser } from '../api/apiClient'

const suggestions = [
  'מי עם הרכב?',
  'הרכב פנוי היום בערב?',
  'תזמין לי את הרכב למחר',
  'מה ההזמנה הבאה?',
]

export function MainAppScreen({ user }: { user: InternalUser }) {
  const [draftMessage, setDraftMessage] = useState('')

  return (
    <main className="main-chat-screen" dir="rtl">
      <header className="main-chat-header">
        <div>
          <strong>Family Car Agent</strong>
          <span>היי, {user.name}</span>
        </div>
        <button type="button" aria-label="הגדרות — בקרוב" disabled>•••</button>
      </header>

      <section className="chat-empty-state">
        <p>העוזר המשפחתי לרכב</p>
        <h1>איך אפשר לעזור?</h1>
        <div className="chat-suggestions" aria-label="הצעות לשאלות">
          {suggestions.map((suggestion) => (
            <button type="button" key={suggestion} onClick={() => setDraftMessage(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
      </section>

      <form className="chat-composer" onSubmit={(event) => event.preventDefault()}>
        <input
          value={draftMessage}
          onChange={(event) => setDraftMessage(event.target.value)}
          placeholder="אפשר לשאול אותי על הרכב..."
          aria-label="הודעה"
        />
        <button type="submit" aria-label="שליחה" disabled>←</button>
      </form>
    </main>
  )
}
