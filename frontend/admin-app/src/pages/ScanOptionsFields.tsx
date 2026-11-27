/** The Scan page's two option groups: how matching behaves, and library upkeep. */
export interface ScanOptionsFieldsProps {
  disabled: boolean
  retryUnmatched: boolean
  setRetryUnmatched: (value: boolean) => void
  recheckMatches: boolean
  setRecheckMatches: (value: boolean) => void
  proposeOnly: boolean
  setProposeOnly: (value: boolean) => void
  removeMissing: boolean
  setRemoveMissing: (value: boolean) => void
  downloadImages: boolean
  setDownloadImages: (value: boolean) => void
  updateExtras: boolean
  setUpdateExtras: (value: boolean) => void
  fetchHltb: boolean
  setFetchHltb: (value: boolean) => void
  forceHltb: boolean
  setForceHltb: (value: boolean) => void
}

export function ScanOptionsFields({
  disabled,
  retryUnmatched,
  setRetryUnmatched,
  recheckMatches,
  setRecheckMatches,
  proposeOnly,
  setProposeOnly,
  removeMissing,
  setRemoveMissing,
  downloadImages,
  setDownloadImages,
  updateExtras,
  setUpdateExtras,
  fetchHltb,
  setFetchHltb,
  forceHltb,
  setForceHltb,
}: ScanOptionsFieldsProps) {
  return (
    <>
      <fieldset className="od-scan-controls__options">
        <legend>Matching</legend>
        <label>
          <input
            type="checkbox"
            checked={retryUnmatched}
            onChange={(event) => setRetryUnmatched(event.target.checked)}
            disabled={disabled}
          />
          <span>
            Retry folders left unmatched
            <small>Turn off to scan only folders this library has not seen before.</small>
          </span>
        </label>
        <label>
          <input
            type="checkbox"
            checked={recheckMatches}
            onChange={(event) => setRecheckMatches(event.target.checked)}
            disabled={disabled || proposeOnly}
          />
          <span>
            Re-check existing matches
            <small>Fixes games whose folder name clearly disagrees with their title.</small>
          </span>
        </label>
        <label>
          <input
            type="checkbox"
            checked={proposeOnly}
            onChange={(event) => setProposeOnly(event.target.checked)}
            disabled={disabled}
          />
          <span>
            Review before adding
            <small>New matches go to Unmatched for review instead of the library.</small>
          </span>
        </label>
      </fieldset>
      <fieldset className="od-scan-controls__options">
        <legend>Library upkeep</legend>
        <label>
          <input
            type="checkbox"
            checked={removeMissing}
            onChange={(event) => setRemoveMissing(event.target.checked)}
            disabled={disabled}
          />
          <span>Remove games whose files are missing</span>
        </label>
        <label>
          <input
            type="checkbox"
            checked={downloadImages}
            onChange={(event) => setDownloadImages(event.target.checked)}
            disabled={disabled}
          />
          <span>Download missing images</span>
        </label>
        <label>
          <input
            type="checkbox"
            checked={updateExtras}
            onChange={(event) => setUpdateExtras(event.target.checked)}
            disabled={disabled}
          />
          <span>Check existing games for new updates and extras</span>
        </label>
        <label>
          <input
            type="checkbox"
            checked={fetchHltb}
            onChange={(event) => setFetchHltb(event.target.checked)}
            disabled={disabled}
          />
          <span>Fetch HowLongToBeat data</span>
        </label>
        <label>
          <input
            type="checkbox"
            checked={forceHltb}
            onChange={(event) => setForceHltb(event.target.checked)}
            disabled={disabled || !fetchHltb}
          />
          <span>Refetch HowLongToBeat for existing games</span>
        </label>
      </fieldset>
    </>
  )
}
