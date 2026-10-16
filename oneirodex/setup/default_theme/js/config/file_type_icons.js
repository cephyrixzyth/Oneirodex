// Semantic kinds consumed by the scan picker. The glyph treatment lives in CSS
// so its foreground follows the active theme instead of depending on an icon font.
export const fileIcons = {
    directory: 'folder',

    // Archives & compressed files
    zip: 'archive',
    rar: 'archive',
    '7z': 'archive',
    gz: 'archive',
    tar: 'archive',

    // Executables & game media
    exe: 'game',
    iso: 'disc',
    bin: 'disc',
    msi: 'game',
    app: 'game',

    // Media
    mp3: 'audio',
    wav: 'audio',
    mp4: 'video',
    avi: 'video',
    mkv: 'video',

    // Documents
    pdf: 'pdf',
    doc: 'document',
    docx: 'document',
    xls: 'spreadsheet',
    xlsx: 'spreadsheet',
    ppt: 'presentation',
    pptx: 'presentation',
    txt: 'text',
    md: 'text',
    cfg: 'text',
    ini: 'text',

    // Images
    jpg: 'image',
    jpeg: 'image',
    png: 'image',
    gif: 'image',

    default: 'file',
};
