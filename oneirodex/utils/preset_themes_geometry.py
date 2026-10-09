"""Per-design geometry tokens for the shipped theme set."""


def _system_geometry(slug: str) -> dict:
    return {
        'greenhouse': {
            'od-radius-xs': '3px', 'od-radius-sm': '6px', 'od-radius-md': '10px',
            'od-radius-lg': '14px', 'od-radius-xl': '18px', 'od-radius-2xl': '24px',
            'od-radius-3xl': '28px', 'od-space-5': '0.9rem',
            'od-shadow-md': '0 8px 22px rgba(0, 24, 12, 0.38)', 'od-motion-base': '180ms',
        },
        'afterglow': {
            'od-radius-xs': '0px', 'od-radius-sm': '2px', 'od-radius-md': '4px',
            'od-radius-lg': '6px', 'od-radius-xl': '8px', 'od-radius-2xl': '10px',
            'od-radius-3xl': '12px', 'od-space-4': '0.5rem', 'od-space-5': '0.68rem',
            'od-shadow-md': '0 4px 0 rgba(0, 0, 0, 0.52)', 'od-motion-base': '110ms',
        },
        'monochrome': {
            'od-radius-xs': '0px', 'od-radius-sm': '1px', 'od-radius-md': '2px',
            'od-radius-lg': '3px', 'od-radius-xl': '4px', 'od-radius-2xl': '5px',
            'od-radius-3xl': '6px', 'od-shadow-sm': 'none', 'od-shadow-md': 'none',
            'od-shadow-lg': 'none', 'od-motion-base': '140ms',
        },
        'signal': {
            'od-radius-xs': '2px', 'od-radius-sm': '4px', 'od-radius-md': '7px',
            'od-radius-lg': '10px', 'od-radius-xl': '13px', 'od-radius-2xl': '17px',
            'od-radius-3xl': '21px', 'od-space-4': '0.55rem',
            'od-shadow-md': '0 7px 18px rgba(30, 16, 4, 0.48)', 'od-motion-base': '170ms',
        },
        'tape-deck': {
            'od-radius-xs': '8px', 'od-radius-sm': '11px', 'od-radius-md': '15px',
            'od-radius-lg': '19px', 'od-radius-xl': '24px', 'od-radius-2xl': '30px',
            'od-radius-3xl': '36px', 'od-space-5': '1.1rem',
            'od-shadow-md': '0 8px 22px rgba(28, 10, 44, 0.44)', 'od-motion-base': '220ms',
        },
        'deep-space': {
            'od-radius-xs': '4px', 'od-radius-sm': '7px', 'od-radius-md': '11px',
            'od-radius-lg': '15px', 'od-radius-xl': '19px', 'od-radius-2xl': '25px',
            'od-radius-3xl': '31px', 'od-space-5': '1.1rem', 'od-space-6': '1.6rem',
            'od-shadow-md': '0 7px 24px rgba(0, 22, 44, 0.42)', 'od-motion-base': '190ms',
        },
    }.get(slug, {})