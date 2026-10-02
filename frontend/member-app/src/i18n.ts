export type MemberLocale = 'en' | 'es'

const STRINGS: Record<MemberLocale, Record<string, string>> = {
  en: {
    'No libraries found. Add a library to get started.':
      'No libraries yet. Add one and Oneirodex starts filling the shelves.',
    'No libraries are available.': "Nothing here yet — an admin hasn't added a library.",
    'No games found in your libraries.':
      "Shelves are up but empty. Nothing's turned up in a scan yet.",
    // A scan *did* finish and matched nothing. Plain voice, not playful: this
    // is a thing that went wrong and the operator has to act on it.
    'A scan finished without matching anything.':
      'A scan finished and matched nothing. Check the scan paths point at game folders.',
    'A scan finished without matching anything. {count} folders are waiting in Unmatched.':
      'A scan finished and matched nothing. {count} folders are waiting in Unmatched.',
    'No games match the current filters.':
      'Nothing made it through those filters. Loosen one and try again.',
    'Unable to load games.': "Couldn't load your catalog. Give it another go.",
    'Unable to refresh games.': "Couldn't refresh. You're still seeing the last good load.",
    'Unable to load filter options.':
      "Couldn't load the filters. You can still browse everything below.",
    Library: 'Library',
    'Game Catalog': 'Game Catalog',
    'Library filters': 'Game Catalog filters',
    'Library selection actions': 'Game Catalog selection actions',
    'Library platform': 'System / console',
    'System / console': 'System / console',
    'IGDB platform': 'Catalog platform',
    'Catalog platform': 'Catalog platform',
    Genre: 'Genre',
    Theme: 'Theme',
    'Game mode': 'Game mode',
    'Player perspective': 'Player perspective',
    'All Libraries': 'All libraries',
    'All Library Platforms': 'All systems',
    'All systems': 'All systems',
    'All IGDB Platforms': 'All catalog platforms',
    'All catalog platforms': 'All catalog platforms',
    Installed: 'Installed',
    Companion: 'Companion',
    'All games': 'All games',
    'Installed only': 'Installed only',
    'Companion installed': 'Companion installed',
    'All Genres': 'All genres',
    'All Themes': 'All themes',
    'All Game Modes': 'All game modes',
    'All Perspectives': 'All perspectives',
    Rating: 'Rating',
    'Sort by': 'Sort by',
    'Sort order': 'Sort order',
    Name: 'Name',
    'Date Released': 'Date released',
    'Date Added': 'Date added',
    Filesize: 'File size',
    Ascending: 'Ascending',
    Descending: 'Descending',
    Apply: 'Apply',
    Clear: 'Clear filters',
    Retry: 'Retry',
    'Per page': 'Per page',
    First: 'First',
    Previous: 'Previous',
    Next: 'Next',
    Last: 'Last',
    'Page {page} of {pages}': 'Page {page} of {pages}',
    Layout: 'Layout',
    Tile: 'Tile',
    Rows: 'Rows',
    Grid: 'Grid',
    // LIB-02 ownership filters and first-run prompt
    Ownership: 'Ownership',
    'Show games by ownership': 'Show games by ownership',
    'Ignore store ownership': 'Ignore store ownership',
    Owned: 'Owned',
    'Recorded as owned in your linked stores or imports':
      'Recorded as owned in your linked stores or imports',
    'Not recorded': 'Not recorded',
    'No linked store or import lists it. This is not proof you do not own it.':
      'No linked store or import lists it. This is not proof you do not own it.',
    Stores: 'Stores',
    'Match stores': 'Match stores',
    'In any selected store': 'In any selected store',
    'In every selected store': 'In every selected store',
    'Games no selected store has recorded. Not proof you do not own them.':
      'Games no selected store has recorded. Not proof you do not own them.',
    'Games no linked store or import has recorded. Not proof you do not own them.':
      'Games no linked store or import has recorded. Not proof you do not own them.',
    'Store setup': 'Store setup',
    'Link your game stores or import a list, and the library will mark what you already own.':
      'Link your game stores or import a list, and the library will mark what you already own.',
    'Set up stores': 'Set up stores',
    'Not now': 'Not now',
  },
  es: {
    'No libraries found. Add a library to get started.':
      'Aún no hay bibliotecas. Agrega una y Oneirodex empezará a llenar los estantes.',
    'No libraries are available.':
      'Todavía no hay nada aquí: un administrador aún no ha agregado una biblioteca.',
    'No games found in your libraries.':
      'Los estantes están listos, pero vacíos. Ningún escaneo ha encontrado nada todavía.',
    'A scan finished without matching anything.':
      'Un escaneo terminó sin encontrar coincidencias. Comprueba que las rutas apunten a carpetas de juegos.',
    'A scan finished without matching anything. {count} folders are waiting in Unmatched.':
      'Un escaneo terminó sin encontrar coincidencias. {count} carpetas están en Sin coincidencia.',
    'No games match the current filters.':
      'Ningún juego pasó esos filtros. Quita alguno y vuelve a intentarlo.',
    'Unable to load games.': 'No se pudo cargar tu catálogo. Inténtalo de nuevo.',
    'Unable to refresh games.': 'No se pudo actualizar. Sigues viendo los últimos datos correctos.',
    'Unable to load filter options.':
      'No se pudieron cargar los filtros. Aun así puedes explorar todo lo de abajo.',
    Library: 'Biblioteca',
    'Game Catalog': 'Catálogo de juegos',
    'Library filters': 'Filtros del catálogo',
    'Library selection actions': 'Acciones de selección del catálogo',
    'Library platform': 'Sistema / consola',
    'System / console': 'Sistema / consola',
    'IGDB platform': 'Plataforma del catálogo',
    'Catalog platform': 'Plataforma del catálogo',
    Genre: 'Género',
    Theme: 'Tema',
    'Game mode': 'Modo de juego',
    'Player perspective': 'Perspectiva',
    'All Libraries': 'Todas las bibliotecas',
    'All Library Platforms': 'Todos los sistemas',
    'All systems': 'Todos los sistemas',
    'All IGDB Platforms': 'Todas las plataformas del catálogo',
    'All catalog platforms': 'Todas las plataformas del catálogo',
    Installed: 'Instalados',
    Companion: 'Companion',
    'All games': 'Todos los juegos',
    'Installed only': 'Solo instalados',
    'Companion installed': 'Instalados en companion',
    'All Genres': 'Todos los géneros',
    'All Themes': 'Todos los temas',
    'All Game Modes': 'Todos los modos',
    'All Perspectives': 'Todas las perspectivas',
    Rating: 'Valoración',
    'Sort by': 'Ordenar por',
    'Sort order': 'Orden',
    Name: 'Nombre',
    'Date Released': 'Fecha de lanzamiento',
    'Date Added': 'Fecha de alta',
    Filesize: 'Tamaño',
    Ascending: 'Ascendente',
    Descending: 'Descendente',
    Apply: 'Aplicar',
    Clear: 'Limpiar filtros',
    Retry: 'Reintentar',
    'Per page': 'Por página',
    First: 'Primera',
    Previous: 'Anterior',
    Next: 'Siguiente',
    Last: 'Última',
    'Page {page} of {pages}': 'Página {page} de {pages}',
    Layout: 'Diseño',
    Tile: 'Portadas',
    Rows: 'Filas',
    Grid: 'Cuadrícula',
    Ownership: 'Propiedad',
    'Show games by ownership': 'Mostrar juegos por propiedad',
    'Ignore store ownership': 'No filtrar por tiendas',
    Owned: 'Comprados',
    'Recorded as owned in your linked stores or imports':
      'Registrados como tuyos en tus tiendas vinculadas o listas importadas',
    'Not recorded': 'Sin registro',
    'No linked store or import lists it. This is not proof you do not own it.':
      'Ninguna tienda vinculada ni lista importada lo incluye. No prueba que no lo tengas.',
    Stores: 'Tiendas',
    'Match stores': 'Coincidencia de tiendas',
    'In any selected store': 'En cualquier tienda elegida',
    'In every selected store': 'En todas las tiendas elegidas',
    'Games no selected store has recorded. Not proof you do not own them.':
      'Juegos que ninguna tienda elegida ha registrado. No prueba que no los tengas.',
    'Games no linked store or import has recorded. Not proof you do not own them.':
      'Juegos que ninguna tienda vinculada ni lista importada ha registrado. No prueba que no los tengas.',
    'Store setup': 'Configurar tiendas',
    'Link your game stores or import a list, and the library will mark what you already own.':
      'Vincula tus tiendas o importa una lista y la biblioteca marcará lo que ya tienes.',
    'Set up stores': 'Configurar tiendas',
    'Not now': 'Ahora no',
  },
}

export function normalizeLocale(locale?: string | null): MemberLocale {
  const raw = (locale || 'en').toLowerCase()
  if (raw.startsWith('es')) return 'es'
  return 'en'
}

export function createTranslator(locale?: string | null) {
  const lang = normalizeLocale(locale)
  const table = STRINGS[lang] || STRINGS.en
  return function t(key: string, vars: Record<string, unknown> = {}) {
    let text = table[key] || STRINGS.en[key] || key
    Object.entries(vars).forEach(([name, value]) => {
      text = text.replace(`{${name}}`, String(value))
    })
    return text
  }
}
