import { getJson, postJson } from './client'

type CompanionTarget = { device_id: string; device_name?: string }

type CommandStatus = {
  id: string
  action: string
  status: string
  target_device_id?: string
  retry_at?: string
}

export async function fetchCompanionQueue(gameUuid: string): Promise<CommandStatus[]> {
  const result = await getJson(
    '/api/client/capabilities?command_game=' + encodeURIComponent(gameUuid),
    {
      label: 'companion queue',
    },
  )
  return Array.isArray(result?.commands) ? result.commands : []
}

async function selectCompanion(): Promise<string | undefined> {
  const result = await getJson('/api/client/capabilities?include_devices=1', {
    label: 'companion devices',
  })
  const devices: CompanionTarget[] = Array.isArray(result?.devices) ? result.devices : []
  if (devices.length < 2) return devices[0]?.device_id
  const dialog = document.createElement('dialog')
  dialog.className = 'od-dialog'
  const heading = document.createElement('h2')
  heading.textContent = 'Choose a companion'
  const form = document.createElement('form')
  form.method = 'dialog'
  const select = document.createElement('select')
  select.setAttribute('aria-label', 'Companion device')
  for (const device of devices) {
    const option = document.createElement('option')
    option.value = device.device_id
    option.textContent = (device.device_name || 'Companion') + ' · ' + device.device_id.slice(-8)
    select.append(option)
  }
  const confirm = document.createElement('button')
  confirm.value = 'continue'
  confirm.textContent = 'Queue on this device'
  const cancel = document.createElement('button')
  cancel.value = 'cancel'
  cancel.textContent = 'Cancel'
  form.append(select, confirm, cancel)
  dialog.append(heading, form)
  document.body.append(dialog)
  return new Promise((resolve, reject) => {
    dialog.addEventListener(
      'close',
      () => {
        const id = select.value
        dialog.remove()
        if (dialog.returnValue === 'continue') resolve(id)
        else reject(new Error('Command canceled.'))
      },
      { once: true },
    )
    dialog.showModal()
  })
}

/**
 * Queue Install / Update / Uninstall / Apply patch / Open path for the desktop companion.
 * @param {string} gameUuid
 * @param {'install' | 'update' | 'uninstall' | 'apply_patch' | 'apply_mod_pack' | 'open_path' | 'download'} action
 * @param {{ kind?: 'base' | 'update' | 'extra', versionUuid?: string, path?: string, select?: boolean }} [options]
 */
export async function queueClientCommand(gameUuid: any, action: any, options: LooseProps = {}) {
  const body: LooseProps = { game_uuid: gameUuid || '', action }
  const target = options.targetDeviceId || (await selectCompanion())
  if (target) body.target_device_id = target
  if (options.kind) {
    body.kind = options.kind
  }
  if (options.versionUuid) {
    body.version_uuid = options.versionUuid
  }
  if (options.path) {
    body.path = options.path
  }
  if (options.select != null) {
    body.select = Boolean(options.select)
  }
  return (await postJson('/api/client/commands', body, { label: 'client/commands' })) ?? {}
}
