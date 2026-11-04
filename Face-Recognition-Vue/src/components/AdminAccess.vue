<template>
    <form class="d-flex flex-column ga-4" style="width: min(420px, 100%); margin: 0 auto" @submit.prevent="login">
        <h2 class="text-h5">Вход администратора</h2>
        <v-text-field v-model="token" type="password" label="Токен администратора"
            autocomplete="off" variant="outlined" hide-details :disabled="busy" />
        <v-alert v-if="error" type="error" variant="tonal">{{ error }}</v-alert>
        <v-btn type="submit" prepend-icon="mdi-login" :loading="busy" :disabled="!token">Войти</v-btn>
    </form>
</template>

<script>
export default {
    emits: ['authorized'],
    data() { return { token: '', busy: false, error: '' }; },
    async mounted() {
        try {
            const response = await fetch('/api/admin/session');
            if (response.ok) this.$emit('authorized');
        } catch { /* Отсутствие сессии не мешает ручному входу */ }
    },
    methods: {
        async login() {
            if (window.location.protocol !== 'https:') {
                this.error = 'Откройте панель по HTTPS';
                return;
            }
            this.busy = true;
            this.error = '';
            try {
                const response = await fetch('/api/admin/login', {
                    method: 'POST', headers: { 'X-Admin-Token': this.token }
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.message || 'Вход не выполнен');
                this.token = '';
                this.$emit('authorized');
            } catch (error) { this.error = error.message; }
            finally { this.busy = false; }
        }
    }
};
</script>
