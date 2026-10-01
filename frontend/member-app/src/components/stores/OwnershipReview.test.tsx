import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { OwnershipReview } from './OwnershipReview'
import { jsonResponse, stubFetch } from '../../testJsonResponse'

/** Focus moves after a poll re-render; allow for a loaded CI box. */
const FOCUS_WAIT = { timeout: 3000 }

const A = '00000000-0000-0000-0000-00000000000a'
const B = '00000000-0000-0000-0000-00000000000b'

function title(overrides: any = {}) {
  return {
    id: 7,
    store: 'gog',
    external_app_id: '1207658924',
    name: 'Same Title',
    matched_game_uuid: null,
    match_available: false,
    match_revision: 0,
    match_reviewed: false,
    ...overrides,
  }
}

const candidates = {
  ok: true,
  title_id: 7,
  match_revision: 0,
  truncated: false,
  candidates: [
    {
      game_uuid: A,
      name: 'Same Title',
      library_uuid: 'l1',
      platform: 'PCWIN',
      basis: 'title_only',
      requires_review: true,
    },
    {
      game_uuid: B,
      name: 'Same Title',
      library_uuid: 'l2',
      platform: 'SWITCH',
      basis: 'title_only',
      requires_review: true,
    },
  ],
}

afterEach(() => vi.unstubAllGlobals())

function renderReview() {
  return render(
    <MemoryRouter>
      <OwnershipReview />
    </MemoryRouter>,
  )
}

test('asks for titles needing review and never picks a candidate for the member', async () => {
  const user = userEvent.setup()
  const fetchMock = stubFetch((url: string) => {
    if (url.includes('/candidates')) return jsonResponse(candidates)
    return jsonResponse({ ok: true, titles: [title()], next_after_id: null })
  })
  renderReview()
  const row = await screen.findByRole('listitem')
  const titleCalls = fetchMock.mock.calls
    .map(([url]) => String(url))
    .filter((url) => url.startsWith('/api/ownership/titles'))
  expect(titleCalls[0]).toBe('/api/ownership/titles?after_id=0&status=needs_review')
  expect(within(row).getByText('Needs review')).toBeInTheDocument()
  expect(within(row).getByText('GOG · ID 1207658924')).toBeInTheDocument()
  await user.click(within(row).getByRole('button', { name: 'Review match' }))
  const options = await within(row).findAllByRole('radio')
  expect(options).toHaveLength(3)
  expect(options.every((o) => !(o as HTMLInputElement).checked)).toBe(true)
  expect(within(row).getByRole('button', { name: 'Confirm' })).toBeDisabled()
  expect(within(row).getByText(/Same Title · SWITCH/)).toBeInTheDocument()
})

test('confirming sends the revision, then the latest decision can be undone', async () => {
  const user = userEvent.setup()
  const fetchMock = stubFetch((url: string, init: any) => {
    if (url.includes('/candidates')) return jsonResponse(candidates)
    if (url.endsWith('/match/undo'))
      return jsonResponse({
        ok: true,
        title_id: 7,
        matched_game_uuid: null,
        match_reviewed: false,
        match_revision: 2,
      })
    if (url.endsWith('/match'))
      return jsonResponse({
        ok: true,
        title_id: 7,
        matched_game_uuid: B,
        match_reviewed: true,
        match_revision: 1,
      })
    return jsonResponse({ ok: true, titles: [title()], next_after_id: null })
  })
  renderReview()
  const row = await screen.findByRole('listitem')
  await user.click(within(row).getByRole('button', { name: 'Review match' }))
  await user.click(await within(row).findByLabelText(/Same Title · SWITCH/))
  await user.click(within(row).getByRole('button', { name: 'Confirm' }))
  const match = fetchMock.mock.calls.find(([url]) =>
    String(url).endsWith('/api/ownership/titles/7/match'),
  )
  expect(JSON.parse(match![1].body)).toEqual({ game_uuid: B, expected_revision: 0 })
  expect(await within(row).findByText('Matched · confirmed')).toBeInTheDocument()
  expect(within(row).getByRole('link', { name: 'Same Title' })).toHaveAttribute(
    'href',
    `/game/${B}`,
  )
  await user.click(within(row).getByRole('button', { name: 'Undo' }))
  const undo = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/match/undo'))
  expect(JSON.parse(undo![1].body)).toEqual({ expected_revision: 1 })
  expect(await within(row).findByText('Needs review')).toBeInTheDocument()
})

test('a stale decision keeps the draft and offers a reload instead of losing the choice', async () => {
  const user = userEvent.setup()
  let listReads = 0
  stubFetch((url: string) => {
    if (url.includes('/candidates')) return jsonResponse(candidates)
    if (url.endsWith('/match')) {
      return jsonResponse(
        {
          ok: false,
          error: 'Ownership decision changed; refresh before retrying',
          error_code: 'conflict',
        },
        { ok: false, status: 409 },
      )
    }
    listReads += 1
    return jsonResponse({
      ok: true,
      titles: [title({ match_revision: listReads > 1 ? 3 : 0 })],
      next_after_id: null,
    })
  })
  renderReview()
  const row = await screen.findByRole('listitem')
  await user.click(within(row).getByRole('button', { name: 'Review match' }))
  const pick = await within(row).findByLabelText(/Same Title · PCWIN/)
  await user.click(pick)
  await user.click(within(row).getByRole('button', { name: 'Confirm' }))
  expect(await within(row).findByRole('alert')).toHaveTextContent(/changed after you opened it/)
  expect(pick).toBeChecked()
  await user.click(within(row).getByRole('button', { name: 'Reload title' }))
  expect(await within(row).findByText(/Your choice is still selected/)).toBeInTheDocument()
  expect(within(row).getByLabelText(/Same Title · PCWIN/)).toBeChecked()
})

test('undo after a re-match names the game the title is linked to again', async () => {
  const user = userEvent.setup()
  const linked = title({
    matched_game_uuid: A,
    match_available: true,
    match_reviewed: true,
    match_revision: 4,
    matched_game: { name: 'Same Title', platform: 'PCWIN' },
  })
  stubFetch((url: string) => {
    if (url.includes('/candidates')) return jsonResponse(candidates)
    if (url.endsWith('/match/undo'))
      return jsonResponse({
        ok: true,
        title_id: 7,
        matched_game_uuid: A,
        match_reviewed: true,
        match_revision: 6,
      })
    if (url.endsWith('/match'))
      return jsonResponse({
        ok: true,
        title_id: 7,
        matched_game_uuid: B,
        match_reviewed: true,
        match_revision: 5,
      })
    return jsonResponse({ ok: true, titles: [linked], next_after_id: null })
  })
  renderReview()
  const row = await screen.findByRole('listitem')
  expect(within(row).getByText(/\(PCWIN\)/)).toBeInTheDocument()
  await user.click(within(row).getByRole('button', { name: 'Review match' }))
  await user.click(await within(row).findByLabelText(/Same Title · SWITCH/))
  await user.click(within(row).getByRole('button', { name: 'Confirm' }))
  expect(await within(row).findByText(/\(SWITCH\)/)).toBeInTheDocument()
  await user.click(within(row).getByRole('button', { name: 'Undo' }))
  expect(await within(row).findByText(/\(PCWIN\)/)).toBeInTheDocument()
  expect(within(row).getByRole('link', { name: 'Same Title' })).toHaveAttribute(
    'href',
    `/game/${A}`,
  )
  expect(within(row).queryByText(/\(SWITCH\)/)).toBeNull()
})

test('an undo refused as stale offers a reload and stops offering the undo', async () => {
  const user = userEvent.setup()
  stubFetch((url: string) => {
    if (url.includes('/candidates')) return jsonResponse(candidates)
    if (url.endsWith('/match/undo')) {
      return jsonResponse(
        {
          ok: false,
          error: 'Ownership decision changed; refresh before retrying',
          error_code: 'conflict',
        },
        { ok: false, status: 409 },
      )
    }
    if (url.endsWith('/match'))
      return jsonResponse({
        ok: true,
        title_id: 7,
        matched_game_uuid: B,
        match_reviewed: true,
        match_revision: 1,
      })
    return jsonResponse({ ok: true, titles: [title()], next_after_id: null })
  })
  renderReview()
  const row = await screen.findByRole('listitem')
  await user.click(within(row).getByRole('button', { name: 'Review match' }))
  await user.click(await within(row).findByLabelText(/Same Title · SWITCH/))
  await user.click(within(row).getByRole('button', { name: 'Confirm' }))
  await user.click(await within(row).findByRole('button', { name: 'Undo' }))
  expect(await within(row).findByRole('alert')).toHaveTextContent(/cannot be undone/)
  expect(within(row).queryByRole('button', { name: 'Undo' })).toBeNull()
  expect(within(row).getByRole('button', { name: 'Reload title' })).toBeEnabled()
})

test('after Confirm, focus stays on the row and a D-pad reaches the choices', async () => {
  const user = userEvent.setup()
  stubFetch((url: string) => {
    if (url.includes('/candidates')) return jsonResponse(candidates)
    if (url.endsWith('/match'))
      return jsonResponse({
        ok: true,
        title_id: 7,
        matched_game_uuid: A,
        match_reviewed: true,
        match_revision: 1,
      })
    return jsonResponse({ ok: true, titles: [title()], next_after_id: null })
  })
  renderReview()
  const row = await screen.findByRole('listitem')
  const toggle = within(row).getByRole('button', { name: 'Review match' })
  toggle.focus()
  await user.keyboard('{Enter}')
  const first = await within(row).findByLabelText(/Same Title · PCWIN/)
  // Down from the toggle enters the choice group; Enter (a controller's A) picks.
  await user.keyboard('{ArrowDown}')
  expect(first).toHaveFocus()
  await user.keyboard('{Enter}')
  expect(first).toBeChecked()
  await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}')
  const confirm = within(row).getByRole('button', { name: 'Confirm' })
  expect(confirm).toHaveFocus()
  await user.keyboard('{Enter}')
  expect(await within(row).findByText('Matched · confirmed')).toBeInTheDocument()
  expect(within(row).getByRole('button', { name: 'Review match' })).toHaveFocus()
})

test('switching the filter while more titles load never mixes in the old filter', async () => {
  const user = userEvent.setup()
  let releaseMore: () => void = () => {}
  stubFetch((url: string) => {
    if (url.includes('status=matched')) {
      return jsonResponse({
        ok: true,
        titles: [title({ id: 30, name: 'Matched three', matched_game_uuid: A })],
        next_after_id: null,
      })
    }
    if (url.includes('after_id=10')) {
      return new Promise((resolve) => {
        releaseMore = () =>
          resolve(
            jsonResponse({
              ok: true,
              titles: [title({ id: 20, name: 'NR two' })],
              next_after_id: 20,
            }),
          )
      })
    }
    return jsonResponse({
      ok: true,
      titles: [title({ id: 10, name: 'NR one' })],
      next_after_id: 10,
    })
  })
  renderReview()
  await screen.findByText('NR one')
  await user.click(screen.getByRole('button', { name: 'Show more' }))
  await user.click(screen.getByRole('button', { name: 'Matched' }))
  await screen.findByText('Matched three')
  releaseMore()
  await new Promise((resolve) => setTimeout(resolve, 20))
  expect(screen.queryByText('NR two')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Show more' })).toBeNull()
  await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(1))
})

test('Reload title, and an undo refused as stale, keep focus on the row', async () => {
  const user = userEvent.setup()
  let matchCalls = 0
  stubFetch((url: string) => {
    if (url.includes('/candidates')) return jsonResponse(candidates)
    if (url.endsWith('/match/undo')) {
      return jsonResponse(
        { ok: false, error: 'changed', error_code: 'conflict' },
        { ok: false, status: 409 },
      )
    }
    if (url.endsWith('/match')) {
      matchCalls += 1
      if (matchCalls === 1)
        return jsonResponse(
          { ok: false, error: 'changed', error_code: 'conflict' },
          { ok: false, status: 409 },
        )
      return jsonResponse({
        ok: true,
        title_id: 7,
        matched_game_uuid: A,
        match_reviewed: true,
        match_revision: 4,
      })
    }
    return jsonResponse({
      ok: true,
      titles: [title({ match_revision: matchCalls ? 3 : 0 })],
      next_after_id: null,
    })
  })
  renderReview()
  const row = await screen.findByRole('listitem')
  await user.click(within(row).getByRole('button', { name: 'Review match' }))
  await user.click(await within(row).findByLabelText(/Same Title · PCWIN/))
  await user.click(within(row).getByRole('button', { name: 'Confirm' }))
  await user.click(await within(row).findByRole('button', { name: 'Reload title' }))
  await waitFor(() =>
    expect(within(row).queryByRole('button', { name: 'Reload title' })).toBeNull(),
  )
  await waitFor(
    () => expect(within(row).getByRole('button', { name: 'Close' })).toHaveFocus(),
    FOCUS_WAIT,
  )
  await user.click(within(row).getByRole('button', { name: 'Confirm' }))
  await user.click(await within(row).findByRole('button', { name: 'Undo' }))
  await waitFor(
    () => expect(within(row).getByRole('button', { name: 'Reload title' })).toHaveFocus(),
    FOCUS_WAIT,
  )
})

test('the arrow keys never fall through to the browser and check a choice at the end of the list', async () => {
  const user = userEvent.setup()
  stubFetch((url: string) => {
    if (url.includes('/candidates')) return jsonResponse(candidates)
    return jsonResponse({ ok: true, titles: [title()], next_after_id: null })
  })
  renderReview()
  const row = await screen.findByRole('listitem')
  await user.click(within(row).getByRole('button', { name: 'Review match' }))
  const none = await within(row).findByLabelText(/None of these/)
  none.focus()
  // Nothing after it can take focus (Confirm waits for a choice): the key is still consumed.
  expect(fireEvent.keyDown(none, { key: 'ArrowDown' })).toBe(false)
  expect(
    within(row)
      .getAllByRole('radio')
      .some((r) => (r as HTMLInputElement).checked),
  ).toBe(false)
})

test('a match to a game the member cannot open is shown as a match, not as needing review', async () => {
  const user = userEvent.setup()
  stubFetch((url: string) => {
    if (url.includes('/candidates')) return jsonResponse({ ...candidates, candidates: [] })
    return jsonResponse({ ok: true, titles: [title({ match_hidden: true })], next_after_id: null })
  })
  renderReview()
  const row = await screen.findByRole('listitem')
  expect(within(row).getByText('Matched · not in your libraries')).toBeInTheDocument()
  expect(within(row).queryByText('Needs review')).toBeNull()
  expect(within(row).getByText(/library you cannot open/)).toBeInTheDocument()
  await user.click(within(row).getByRole('button', { name: 'Review match' }))
  expect(
    await within(row).findByLabelText(/Remove this match \(you cannot undo this/),
  ).toBeInTheDocument()
})

test('removing a hidden match clears its label and offers no Undo the server would refuse', async () => {
  const user = userEvent.setup()
  stubFetch((url: string) => {
    if (url.includes('/candidates')) return jsonResponse({ ...candidates, candidates: [] })
    if (url.endsWith('/match'))
      return jsonResponse({
        ok: true,
        title_id: 7,
        matched_game_uuid: null,
        match_reviewed: true,
        match_revision: 1,
      })
    return jsonResponse({ ok: true, titles: [title({ match_hidden: true })], next_after_id: null })
  })
  renderReview()
  const row = await screen.findByRole('listitem')
  await user.click(within(row).getByRole('button', { name: 'Review match' }))
  await user.click(await within(row).findByLabelText(/Remove this match/))
  await user.click(within(row).getByRole('button', { name: 'Confirm' }))
  expect(await within(row).findByText('No match · confirmed')).toBeInTheDocument()
  expect(within(row).queryByText(/library you cannot open/)).toBeNull()
  expect(within(row).queryByRole('button', { name: 'Undo' })).toBeNull()
})

test('an undo the server refuses outright is withdrawn instead of failing on every press', async () => {
  const user = userEvent.setup()
  stubFetch((url: string) => {
    if (url.includes('/candidates')) return jsonResponse(candidates)
    if (url.endsWith('/match/undo')) {
      return jsonResponse(
        { ok: false, error: 'Library game not available', error_code: 'not_found' },
        { ok: false, status: 404 },
      )
    }
    if (url.endsWith('/match'))
      return jsonResponse({
        ok: true,
        title_id: 7,
        matched_game_uuid: B,
        match_reviewed: true,
        match_revision: 1,
      })
    return jsonResponse({ ok: true, titles: [title()], next_after_id: null })
  })
  renderReview()
  const row = await screen.findByRole('listitem')
  await user.click(within(row).getByRole('button', { name: 'Review match' }))
  await user.click(await within(row).findByLabelText(/Same Title · SWITCH/))
  await user.click(within(row).getByRole('button', { name: 'Confirm' }))
  await user.click(await within(row).findByRole('button', { name: 'Undo' }))
  expect(await within(row).findByRole('alert')).toHaveTextContent('Library game not available')
  expect(within(row).queryByRole('button', { name: 'Undo' })).toBeNull()
})

test('left and right on a candidate move like up and down and never check a choice', async () => {
  const user = userEvent.setup()
  stubFetch((url: string) => {
    if (url.includes('/candidates')) return jsonResponse(candidates)
    return jsonResponse({ ok: true, titles: [title()], next_after_id: null })
  })
  renderReview()
  const row = await screen.findByRole('listitem')
  await user.click(within(row).getByRole('button', { name: 'Review match' }))
  const [first, second] = await within(row).findAllByRole('radio')
  first.focus()
  expect(fireEvent.keyDown(first, { key: 'ArrowRight' })).toBe(false)
  expect(second).toHaveFocus()
  expect(fireEvent.keyDown(second, { key: 'ArrowLeft' })).toBe(false)
  expect(first).toHaveFocus()
  expect(
    within(row)
      .getAllByRole('radio')
      .some((r) => (r as HTMLInputElement).checked),
  ).toBe(false)
})
