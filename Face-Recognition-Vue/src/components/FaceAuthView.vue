<template>
    <div v-if="!authorized" class="admin-login">
        <AdminAccess @authorized="onAuthorized" />
    </div>
    <div v-else class="admin-layout">
        <aside class="admin-nav" aria-label="Разделы администратора">
            <div class="nav-group">Управление</div>
            <v-list density="comfortable" nav class="pa-0 bg-transparent">
                <v-list-item v-for="item in sections" :key="item.id" :active="tab === item.id"
                    :prepend-icon="item.icon" :title="item.title" @click="tab = item.id" />
            </v-list>
            <v-divider class="my-4" />
            <v-btn variant="text" prepend-icon="mdi-logout" :loading="checking" @click="logout">Выйти</v-btn>
            <p v-if="sessionError" class="text-error text-body-2 mt-2" role="alert">{{ sessionError }}</p>
        </aside>
        <section class="admin-workspace">
            <div class="workspace-heading">
                <h1>{{ currentSection.title }}</h1>
                <p>{{ currentSection.description }}</p>
            </div>
            <FaceAuthentication v-if="tab === 'auth'" @maintenance="tab = 'calibration'" />
            <UsersManagement v-else-if="tab === 'users'" />
            <StereoCalibration v-else-if="tab === 'calibration'" />
            <ChallengeVerification v-else-if="tab === 'challenge'" />
            <AccessHistory v-else-if="tab === 'journal'" />
        </section>
    </div>
</template>

<script>
import FaceAuthentication from './FaceAuthentication.vue';
import UsersManagement from './UsersManagement.vue';
import StereoCalibration from './StereoCalibration.vue';
import AdminAccess from './AdminAccess.vue';
import ChallengeVerification from './ChallengeVerification.vue';
import AccessHistory from './AccessHistory.vue';

export default {
    name: 'FaceAuthView',
    components: { FaceAuthentication, UsersManagement, StereoCalibration, AdminAccess, ChallengeVerification, AccessHistory },
    data() {
        return { tab: 'auth', authorized: false, checking: false, sessionError: '', timer: null, sections: [
            { id: 'auth', title: 'Мониторинг', icon: 'mdi-monitor-eye', description: 'Камеры, состояние системы и текущая попытка прохода.' },
            { id: 'users', title: 'Пользователи', icon: 'mdi-account-group-outline', description: 'Регистрация и удаление биометрических шаблонов.' },
            { id: 'journal', title: 'Журнал и политика', icon: 'mdi-clipboard-text-outline', description: 'История проходов и правила аутентификации.' },
            { id: 'calibration', title: 'Калибровка камер', icon: 'mdi-camera-cog-outline', description: 'Настройка стереопары и проверка её точности.' },
            { id: 'challenge', title: 'Тест заданий', icon: 'mdi-eye-check-outline', description: 'Экспериментальная проверка действий без открытия замка.' },
        ] };
    },
    computed: { currentSection() { return this.sections.find(item => item.id === this.tab) || this.sections[0]; } },
    mounted() {
        this.timer = window.setInterval(this.checkSession, 15000);
        window.addEventListener('focus', this.checkSession);
    },
    beforeUnmount() {
        window.clearInterval(this.timer);
        window.removeEventListener('focus', this.checkSession);
    },
    methods: {
        onAuthorized() { this.authorized = true; this.sessionError = ''; },
        async checkSession() {
            if (!this.authorized || this.checking || document.hidden) return;
            try {
                const response = await fetch('/api/admin/session', { cache: 'no-store' });
                if (response.status === 401 || response.status === 403) this.authorized = false;
            } catch { /* Network errors must not be treated as successful authorization. */ }
        },
        async logout() {
            if (this.checking) return;
            this.checking = true;
            this.sessionError = '';
            try {
                const response = await fetch('/api/admin/logout', { method: 'POST' });
                if (!response.ok && response.status !== 401) throw new Error('Не удалось завершить сессию');
                this.authorized = false;
                this.tab = 'auth';
                this.$router.push('/');
            } catch (error) { this.sessionError = error.message; }
            finally { this.checking = false; }
        }
    }
};
</script>

<style scoped>
.admin-login { max-width: 480px; margin: 64px auto; padding: 0 16px; }
.admin-layout { max-width: 1440px; margin: 0 auto; display: grid; grid-template-columns: 230px minmax(0, 1fr); gap: 28px; padding: 24px; align-items: start; }
.admin-nav { position: sticky; top: 16px; padding: 12px 0; }
.nav-group { padding: 0 12px 10px; color: #56616c; font-size: 13px; font-weight: 600; }
.admin-workspace { min-width: 0; }
.workspace-heading { margin-bottom: 20px; }
.workspace-heading h1 { font-size: 26px; font-weight: 650; line-height: 1.25; }
.workspace-heading p { color: #56616c; margin-top: 6px; }
@media (max-width: 760px) {
    .admin-layout { display: block; padding: 12px; }
    .admin-nav { position: static; margin-bottom: 16px; border-bottom: 1px solid #dce1e5; }
    .admin-nav :deep(.v-list) { display: grid; grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); gap: 4px; }
    .admin-nav :deep(.v-list-item-title) { white-space: normal; font-size: 14px; }
}
</style>
