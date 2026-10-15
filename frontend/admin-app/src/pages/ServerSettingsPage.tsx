import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { getJson, putJson } from '../api/adminApi'
import { Page } from '../components/Page'
import { errorText } from '../utils/errorText'

const API = '/api/admin/server-settings'
type Field = { key: string; label: string; type?: 'text' | 'url' | 'number'; help?: string }
export const SERVER_SETTING_GROUPS: { title: string; fields: Field[] }[] = [
  {
    title: 'Core features',
    fields: [
      {
        key: 'allowUsersToInviteOthers',
        label: 'Enable user invite system',
        help: 'Allow regular users to invite new members.',
      },
      {
        key: 'enableServerStatusFeature',
        label: 'Enable server info feature',
        help: 'Make administrator server diagnostics available.',
      },
      {
        key: 'enableNewsletterFeature',
        label: 'Enable newsletter feature',
        help: 'Allow administrators to prepare newsletters.',
      },
      {
        key: 'enableDeleteGameOnDisk',
        label: 'Enable delete game on disk',
        help: 'Make disk deletion available in game actions. Saving this preference does not delete files.',
      },
      {
        key: 'showPlayStatus',
        label: 'Enable play status tracking',
        help: 'Track unplayed, unfinished, beaten and completed games.',
      },
      {
        key: 'siteUrl',
        label: 'Site URL',
        type: 'url',
        help: 'The HTTP or HTTPS base URL used for this server.',
      },
    ],
  },
  {
    title: 'Scanning and performance',
    fields: [
      { key: 'enableGameUpdates', label: 'Enable game updates scanning' },
      { key: 'updateFolderName', label: 'Updates folder name', type: 'text' },
      { key: 'enableGameExtras', label: 'Enable extra files scanning' },
      { key: 'extrasFolderName', label: 'Extras folder name', type: 'text' },
      {
        key: 'scanThreadCount',
        label: 'Game scan threads',
        type: 'number',
        help: 'More threads increase CPU and network use. Runtime worker caps still apply.',
      },
      {
        key: 'useTurboImageDownloads',
        label: 'Multithreaded image downloads',
        help: 'When disabled, images download sequentially.',
      },
      {
        key: 'turboDownloadThreads',
        label: 'Image download threads',
        type: 'number',
        help: 'Runtime caps may reduce this configured limit.',
      },
      {
        key: 'turboDownloadBatchSize',
        label: 'Image download batch size',
        type: 'number',
        help: 'Runtime caps may reduce this configured batch size.',
      },
    ],
  },
  {
    title: 'HowLongToBeat',
    fields: [
      {
        key: 'enableHltbIntegration',
        label: 'Enable HLTB integration',
        help: 'Fetch completion-time estimates during scanning.',
      },
      { key: 'hltbRateLimitDelay', label: 'HLTB rate limit delay (seconds)', type: 'number' },
    ],
  },
  {
    title: 'Local metadata and images',
    fields: [
      {
        key: 'useLocalMetadata',
        label: 'Use local metadata on scan',
        help: 'Read saved game identification before searching for metadata.',
      },
      {
        key: 'writeLocalMetadata',
        label: 'Write metadata file on manual ID',
        help: 'Requires write permission to game folders. Saving this preference does not write files.',
      },
      {
        key: 'useLocalImages',
        label: 'Use local images',
        help: 'Prefer local artwork such as cover.jpg over downloaded images.',
      },
      {
        key: 'localMetadataFilename',
        label: 'Metadata filename',
        type: 'text',
        help: 'A .json filename stored inside each game folder.',
      },
    ],
  },
  {
    title: 'Scan behavior',
    fields: [
      {
        key: 'proposeOnlyScan',
        label: 'Propose-only scan mode',
        help: 'Create proposals for review instead of automatically importing matches, including high-confidence matches.',
      },
    ],
  },
  {
    title: 'Interface',
    fields: [
      { key: 'showSystemLogo', label: 'Show system logo' },
      { key: 'showHelpButton', label: 'Show help button' },
      { key: 'enableWebLinksOnDetailsPage', label: 'Show web links on details page' },
      { key: 'showVersion', label: 'Show version' },
      { key: 'showDiscovery', label: 'Show discovery' },
      { key: 'showFavorites', label: 'Show favorites' },
      { key: 'showTrailers', label: 'Show trailers' },
    ],
  },
]
const FIELDS = SERVER_SETTING_GROUPS.flatMap((group) => group.fields)
export function ServerSettingsPage() {
  const [draft, setDraft] = useState<Record<string, any> | null>(null)
  const [saved, setSaved] = useState<Record<string, any> | null>(null)
  const [bounds, setBounds] = useState<Record<string, any>>({})
  const [textLimits, setTextLimits] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  function accept(data: any) {
    if (
      !data?.settings ||
      !data.bounds ||
      !data.text_limits ||
      FIELDS.some(
        (field) =>
          typeof data.settings[field.key] !==
          (field.type === 'number' ? 'number' : field.type ? 'string' : 'boolean'),
      )
    )
      throw new Error('Server settings returned an invalid response.')
    setDraft(data.settings)
    setSaved(data.settings)
    setBounds(data.bounds)
    setTextLimits(data.text_limits)
  }
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadFailed(false)
    setError('')
    getJson(API)
      .then((data) => {
        if (!cancelled) accept(data)
      })
      .catch((err) => {
        if (!cancelled) {
          setLoadFailed(true)
          setError(errorText(err))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [reload])
  const changes =
    draft && saved
      ? Object.fromEntries(
          FIELDS.filter((field) => draft[field.key] !== saved[field.key]).map((field) => [
            field.key,
            draft[field.key],
          ]),
        )
      : {}
  async function save(event: FormEvent) {
    event.preventDefault()
    if (loading || loadFailed || lock.current || !Object.keys(changes).length) return
    lock.current = true
    setBusy(true)
    setError('')
    setMessage('')
    try {
      accept(await putJson(API, changes))
      setMessage('Server settings saved.')
    } catch (err) {
      setError(errorText(err) || 'Could not save server settings.')
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  function edit(key: string, value: any) {
    setDraft((current) => ({ ...current, [key]: value }))
    setMessage('')
  }
  const disabled = loading || loadFailed || busy
  return (
    <Page
      title="Server settings"
      lede="Configure server features, scan preferences, performance, and interface options."
    >
      <PageStatus
        loading={loading}
        loadingMessage="Loading server settings…"
        error={error || null}
      />
      {loadFailed ? (
        <Button onClick={() => setReload((value) => value + 1)}>
          Retry loading server settings
        </Button>
      ) : null}
      {message ? (
        <PageStatus announcement="status" className="od-admin-hint">
          {message}
        </PageStatus>
      ) : null}
      {draft ? (
        <form onSubmit={save}>
          <div className="od-admin-actions-row">
            <Button
              type="submit"
              variant="primary"
              disabled={disabled || !Object.keys(changes).length}
            >
              {busy ? 'Saving…' : 'Save settings'}
            </Button>
          </div>
          {SERVER_SETTING_GROUPS.map((group) => (
            <fieldset key={group.title} className="od-admin-panel" disabled={disabled}>
              <legend>{group.title}</legend>
              {group.fields.map((field) => (
                <div key={field.key} className="od-admin-field">
                  <label htmlFor={`server-${field.key}`}>
                    {!field.type ? (
                      <input
                        id={`server-${field.key}`}
                        type="checkbox"
                        checked={draft[field.key]}
                        onChange={(event) => edit(field.key, event.target.checked)}
                        aria-describedby={field.help ? `server-${field.key}-help` : undefined}
                      />
                    ) : null}{' '}
                    {field.label}
                  </label>
                  {field.type ? (
                    <input
                      id={`server-${field.key}`}
                      className="od-admin-input"
                      type={field.type}
                      required
                      maxLength={textLimits[field.key]}
                      {...bounds[field.key]}
                      value={draft[field.key]}
                      aria-describedby={field.help ? `server-${field.key}-help` : undefined}
                      onChange={(event) =>
                        edit(
                          field.key,
                          field.type === 'number'
                            ? event.target.value === ''
                              ? ''
                              : Number(event.target.value)
                            : event.target.value,
                        )
                      }
                    />
                  ) : null}
                  {field.help ? (
                    <p id={`server-${field.key}-help`} className="od-admin-hint">
                      {field.help}
                    </p>
                  ) : null}
                </div>
              ))}
              {group.title === 'Scan behavior' ? (
                <p className="od-admin-hint">
                  Configure match thresholds and naming variants in{' '}
                  <a href="/admin/scan_match">Scan / match policy</a>.
                </p>
              ) : null}
            </fieldset>
          ))}
          <div className="od-admin-actions-row">
            <Button
              type="submit"
              variant="primary"
              disabled={disabled || !Object.keys(changes).length}
            >
              Save settings
            </Button>
          </div>
        </form>
      ) : null}
      <a href="/admin/dashboard">Back to admin</a>
    </Page>
  )
}
