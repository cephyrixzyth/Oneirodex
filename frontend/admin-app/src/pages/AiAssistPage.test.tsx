import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { AiAssistPage } from './AiAssistPage'
import { getJson, postJson, putJson } from '../api/adminApi'
import { confirmAction } from '@oneirodex/ui'

vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), postJson: vi.fn(), putJson: vi.fn() }))
vi.mock('@oneirodex/ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@oneirodex/ui')>()
  return { ...actual, confirmAction: vi.fn() }
})
afterEach(() => {
  vi.resetAllMocks()
})

const config = {
  enabled: true,
  db_enabled: true,
  env_enabled: false,
  ollama_base_url: 'http://127.0.0.1:11434',
  ollama_model: 'llama3.2',
  auto_apply_enabled: true,
}

test('loads config, saves through API, and contacts local Ollama only on explicit test', async () => {
  vi.mocked(getJson).mockResolvedValue(config)
  vi.mocked(putJson).mockResolvedValue({ ...config, ollama_model: 'qwen2.5' })
  vi.mocked(getJson).mockImplementation(async (url) =>
    url === '/api/ai/config'
      ? config
      : { enabled: true, auto_apply_enabled: true, reachable: true, model: 'llama3.2' },
  )
  render(<AiAssistPage />)
  const model = await screen.findByDisplayValue('llama3.2')
  fireEvent.change(model, { target: { value: 'qwen2.5' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  await waitFor(() =>
    expect(putJson).toHaveBeenCalledWith(
      '/api/ai/config',
      expect.objectContaining({ ollama_model: 'qwen2.5' }),
    ),
  )
  expect(getJson).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
  await waitFor(() => expect(getJson).toHaveBeenCalledWith('/api/ai/status'))
})

test('selects a suggestion and requires confirmation before applying a title', async () => {
  vi.mocked(getJson).mockResolvedValue(config)
  vi.mocked(postJson).mockResolvedValue({ suggestions: [{ title: 'Celeste' }] })
  vi.mocked(confirmAction).mockResolvedValue(false)
  render(<AiAssistPage />)
  fireEvent.change(await screen.findByLabelText('Folder or title'), {
    target: { value: 'Celeste-[Repack]' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Suggest matches' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Celeste' }))
  fireEvent.change(screen.getByLabelText('Existing game UUID'), { target: { value: 'game-uuid' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply title…' }))
  await waitFor(() => expect(confirmAction).toHaveBeenCalled())
  expect(postJson).not.toHaveBeenCalledWith('/api/ai/apply-triage', expect.anything())
  vi.mocked(confirmAction).mockResolvedValue(true)
  fireEvent.click(screen.getByRole('button', { name: 'Apply title…' }))
  await waitFor(() =>
    expect(postJson).toHaveBeenCalledWith('/api/ai/apply-triage', {
      game_uuid: 'game-uuid',
      title: 'Celeste',
    }),
  )
})

test('keeps apply disabled when the environment gate is off', async () => {
  vi.mocked(getJson).mockResolvedValue({ ...config, auto_apply_enabled: false })
  render(<AiAssistPage />)
  expect(await screen.findByRole('button', { name: 'Apply title…' })).toBeDisabled()
})
