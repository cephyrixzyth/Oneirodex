"""The served theme must be reported when it is not the theme we shipped.

Theme CSS/JS only reaches `static/library/themes/` when an admin runs Reset
Themes. After any release that touches theme assets the product keeps serving
the previous copy, and nothing said so — the only symptom was "the fix didn't
work", which sends everyone to read the stylesheet rather than the copy step.

On the install these were written against, 36 of 85 tracked assets were behind
source and 3 had never been deployed at all — including od-shell.css, the entire
rail and shell stylesheet. Every CSS fix in that file had been invisible since
it was written.
"""

from oneirodex.utils.theme_freshness import theme_freshness


def _write(path, text='body { color: red }'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


class TestThemeFreshness:


    def test_a_never_deployed_file_is_missing_not_fresh(self, tmp_path):
        """The od-shell.css case: a new file no reset has ever copied."""
        _write(tmp_path / 'setup' / 'default_theme' / 'css' / 'od-shell.css')

        data = theme_freshness(tmp_path)

        assert data['stale'] is True
        assert data['missing'] == ['css/od-shell.css']
        assert data['outdated_count'] == 0

    def test_only_css_and_js_are_tracked(self, tmp_path):
        """An operator swapping artwork is supported, not drift worth reporting."""
        source = tmp_path / 'setup' / 'default_theme'
        _write(source / 'css' / 'a.css')
        (source / 'images').mkdir(parents=True, exist_ok=True)
        (source / 'images' / 'logo.png').write_bytes(b'\x89PNG source')
        deployed = tmp_path / 'static' / 'library' / 'themes' / 'default'
        _write(deployed / 'css' / 'a.css')
        (deployed / 'images').mkdir(parents=True, exist_ok=True)
        (deployed / 'images' / 'logo.png').write_bytes(b'\x89PNG operator edit')

        data = theme_freshness(tmp_path)

        assert data['checked'] == 1
        assert data['stale'] is False

    def test_a_theme_never_deployed_reports_everything_missing(self, tmp_path):
        """Not 'fresh because there is nothing to compare'."""
        _write(tmp_path / 'setup' / 'default_theme' / 'css' / 'a.css')
        _write(tmp_path / 'setup' / 'default_theme' / 'js' / 'b.js', 'var x = 1')

        data = theme_freshness(tmp_path, theme='ember')

        assert data['checked'] == 2
        assert data['missing_count'] == 2
        assert data['stale'] is True


    def test_long_lists_are_capped_but_counts_are_not(self, tmp_path):
        """An undeployed theme must not dump a hundred paths into an Ops panel."""
        for i in range(30):
            _write(tmp_path / 'setup' / 'default_theme' / 'css' / f'f{i}.css')

        data = theme_freshness(tmp_path)

        assert data['missing_count'] == 30
        assert len(data['missing']) == 20
