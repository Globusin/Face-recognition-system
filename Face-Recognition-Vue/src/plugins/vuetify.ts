import 'vuetify/styles'
import '@mdi/font/css/materialdesignicons.css'
import { createVuetify } from 'vuetify'
import { aliases, mdi } from 'vuetify/iconsets/mdi'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

export default createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: 'domovoy',
    themes: {
      domovoy: { dark: false, colors: { background: '#f4f6f8', surface: '#ffffff', primary: '#344d65', secondary: '#5c6976', success: '#287348', warning: '#9a640e', error: '#b33d3d', info: '#35658d' } },
    },
  },
  defaults: {
    VBtn: { color: 'primary', variant: 'flat', rounded: 'sm' },
    VCard: { elevation: 0, rounded: 'sm' },
    VTextField: { variant: 'outlined', density: 'comfortable', color: 'primary' },
    VSelect: { variant: 'outlined', density: 'comfortable', color: 'primary' },
    VChip: { rounded: 'sm' },
  },
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: {
      mdi
    },
  },
})
