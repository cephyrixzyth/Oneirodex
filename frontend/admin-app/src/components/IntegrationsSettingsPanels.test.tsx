import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { getJson, putJson } from '../api/adminApi'
import { CommunityChatSettingsPanel } from './CommunityChatSettingsPanel'
import { MetadataProvidersSettingsPanel } from './MetadataProvidersSettingsPanel'

vi.mock('../api/adminApi', () => ({ getJson: vi.fn(), putJson: vi.fn() }))

beforeEach(() => {
  vi.mocked(getJson).mockReset()
  vi.mocked(putJson).mockReset()
})

test('metadata provider controls load current values and save changes', async () => {
  vi.mocked(getJson).mockResolvedValue({
    providers: { steam: true, gog: false, epic: true, hash_identify: false },
  })
  vi.mocked(putJson).mockResolvedValue({
    providers: { steam: false, gog: false, epic: true, hash_identify: false },
  })
  render(<MetadataProvidersSettingsPanel />)

  expect(await screen.findByLabelText(/Steam/)).toBeChecked()
  expect(screen.getByLabelText(/GOG/)).not.toBeChecked()
  fireEvent.click(screen.getByLabelText(/Steam/))
  fireEvent.click(screen.getByRole('button', { name: 'Save metadata providers' }))

  await waitFor(() =>
    expect(putJson).toHaveBeenCalledWith('/api/admin/integrations/metadata-providers', {
      providers: { steam: false, gog: false, epic: true, hash_identify: false },
    }),
  )
  expect(await screen.findByText('Metadata provider settings saved.')).toBeInTheDocument()
})

test('community settings save the optional link and expose related admin pages', async () => {
  vi.mocked(getJson).mockResolvedValue({
    community_chat_url: '',
    community_chat_label: 'Open community',
  })
  vi.mocked(putJson).mockResolvedValue({
    community_chat_url: 'https://chat.example.test/invite',
    community_chat_label: 'Join chat',
  })
  render(<CommunityChatSettingsPanel />)

  fireEvent.change(await screen.findByLabelText('Community URL'), {
    target: { value: 'https://chat.example.test/invite' },
  })
  fireEvent.change(screen.getByLabelText('Link label'), { target: { value: 'Join chat' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save community link' }))

  await waitFor(() =>
    expect(putJson).toHaveBeenCalledWith('/api/admin/integrations/community', {
      community_chat_url: 'https://chat.example.test/invite',
      community_chat_label: 'Join chat',
    }),
  )
  expect(await screen.findByText('Community link saved.')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Manage custom chat emoji' })).toHaveAttribute(
    'href',
    '/admin/chat_emoji',
  )
  expect(screen.getByRole('link', { name: 'ROM reference sets' })).toHaveAttribute(
    'href',
    '/admin/reference_sets',
  )
})
