import { Page } from '../components/Page'
import './ThemeAuthoringPage.css'

export function ThemeAuthoringPage() {
  return (
    <Page
      className="od-theme-guide"
      title="Creating Your Own Theme"
      lede="Package a ZIP with theme.json and CSS at the archive root, then upload it from Manage Themes."
    >
      <section className="od-admin-panel">
        <h2>Theme structure</h2>
        <p>A theme pack includes:</p>
        <ul>
          <li>A ZIP file containing the theme files</li>
          <li>
            A <code>theme.json</code> file with theme metadata
          </li>
          <li>
            CSS files in a <code>css</code> folder
          </li>
          <li>
            Optional image files in an <code>images</code> folder
          </li>
        </ul>
      </section>

      <section className="od-admin-panel">
        <h2>theme.json format</h2>
        <pre className="od-admin-output">
          <code>{`{
  "name": "Your Theme Name",
  "author": "Your Name",
  "description": "A brief description of your theme",
  "version": "1.0.0",
  "release_date": "YYYY-MM-DD"
}`}</code>
        </pre>
      </section>

      <section className="od-admin-panel">
        <h2>CSS files</h2>
        <p>
          Place CSS in the <code>css</code> folder. The main file is <code>base.css</code>;
          additional files can be organized in subfolders.
        </p>
      </section>

      <section className="od-admin-panel">
        <h2>Creating the ZIP file</h2>
        <p>
          <strong>Important:</strong> Put theme files at the archive root, not inside an extra
          folder.
        </p>
        <ol>
          <li>Create a folder with your theme name for organization.</li>
          <li>
            Add <code>theme.json</code> to that folder.
          </li>
          <li>
            Create a <code>css</code> subfolder and add your CSS files.
          </li>
          <li>
            Optionally, add an <code>images</code> subfolder for theme images.
          </li>
          <li>
            When creating the ZIP, select the contents of your theme folder. Do not zip the folder
            itself.
          </li>
        </ol>
        <h3>Correct ZIP structure</h3>
        <pre className="od-admin-output">
          <code>{`mytheme.zip
├── theme.json
├── css/
│   ├── base.css
│   ├── components.css
│   └── admin/
│       └── admin_dashboard.css
└── js/                (optional)
    └── custom.js`}</code>
        </pre>
        <h3>Incorrect ZIP structure</h3>
        <pre className="od-admin-output">
          <code>{`mytheme.zip
└── mytheme/           (extra folder layer; upload will fail)
    ├── theme.json
    ├── css/
    └── js/`}</code>
        </pre>
      </section>

      <section className="od-admin-panel">
        <h2>Uploading your theme</h2>
        <p>Use the ZIP upload form on the Manage Themes page to install your theme.</p>
        <a className="od-btn" href="/admin/themes">
          Back to Themes
        </a>
      </section>
    </Page>
  )
}
