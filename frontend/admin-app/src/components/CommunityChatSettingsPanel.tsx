import { useEffect, useState, type FormEvent } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { getJson, putJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'

const ENDPOINT = '/api/admin/integrations/community'

export function CommunityChatSettingsPanel() {
  const [url, setUrl] = useState('')
  const [label, setLabel] = useState('Open community')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    let live = true
    getJson(ENDPOINT)
      .then((data) => {
        if (live) {
          setUrl(String(data.community_chat_url || ''))
          setLabel(String(data.community_chat_label || 'Open community'))
        }
      })
      .catch((cause) => {
        if (live) setError(errorText(cause) || 'Could not load the community link.')
      })
      .finally(() => {
        if (live) setLoading(false)
      })
    return () => {
      live = false
    }
  }, [])

  async function save(event: FormEvent) {
    event.preventDefault()
    if (loading || busy) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const data = await putJson(ENDPOINT, {
        community_chat_url: url.trim(),
        community_chat_label: label.trim(),
      })
      setUrl(String(data.community_chat_url || ''))
      setLabel(String(data.community_chat_label || 'Open community'))
      setMessage('Community link saved.')
    } catch (cause) {
      setError(errorText(cause) || 'Could not save the community link.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      id="community"
      className="od-admin-panel od-admin-panel--stacked"
      aria-labelledby="od-community-chat-title"
    >
      <h2 id="od-community-chat-title" className="od-admin-panel-title">
        Community chat link
      </h2>
      <p className="od-admin-lede">
        Add an optional Stoat or Matrix link for household members. This link does not connect an
        account or share credentials.
      </p>
      <PageStatus
        loading={loading}
        loadingMessage="Loading community link…"
        error={error || null}
        announcement={message ? 'status' : undefined}
      >
        {message}
      </PageStatus>
      <form onSubmit={save}>
        <fieldset className="od-admin-fieldset" disabled={loading || busy}>
          <legend>Public link</legend>
          <label className="od-admin-field">
            Community URL
            <input
              className="od-admin-input"
              type="url"
              maxLength={2048}
              value={url}
              onChange={(event) => setUrl(event.target.value)}
            />
          </label>
          <label className="od-admin-field">
            Link label
            <input
              className="od-admin-input"
              maxLength={120}
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
          </label>
        </fieldset>
        <p className="od-admin-hint">Leave the URL blank to remove the link.</p>
        <div className="od-admin-actions">
          <Button className="od-btn--accent" type="submit" disabled={loading || busy}>
            {busy ? 'Saving…' : 'Save community link'}
          </Button>
          <a className="od-cbtn" href="/admin/chat_emoji">
            Manage custom chat emoji
          </a>
          <a className="od-cbtn" href="/admin/reference_sets">
            ROM reference sets
          </a>
        </div>
      </form>
    </section>
  )
}
