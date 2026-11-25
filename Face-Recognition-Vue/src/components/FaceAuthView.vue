<template>
    <div class="d-flex flex-column ga-6">
        <AdminAccess v-if="!authorized" @authorized="authorized = true" />
        <template v-else>
        <div class="d-flex justify-end ga-2">
            <v-btn to="/" variant="text" prepend-icon="mdi-monitor-eye">Состояние</v-btn>
            <v-btn prepend-icon="mdi-logout" variant="text" @click="logout">Выйти</v-btn>
        </div>
        <div class="d-flex justify-center">
            <v-tabs v-model="tab" inset>
                <v-tab value="auth">
                    <div class="tab-content">
                        <v-icon icon="mdi-face-recognition"></v-icon>
                        <span>Аутентификация</span>
                    </div>
                </v-tab>
                <v-tab value="users">
                    <div class="tab-content">
                        <v-icon icon="mdi-account-group"></v-icon>
                        <span>Пользователи</span>
                    </div>
                </v-tab>
                <v-tab value="calibration">
                    <div class="tab-content">
                        <v-icon icon="mdi-chess-board"></v-icon>
                        <span>Калибровка</span>
                    </div>
                </v-tab>
                <v-tab value="challenge"><v-icon icon="mdi-eye-check" class="mr-2" />Задания</v-tab>
                <v-tab value="journal"><v-icon icon="mdi-clipboard-text-clock" class="mr-2" />Журнал</v-tab>
            </v-tabs>
        </div>
        <KeepAlive>
            <FaceAuthentication v-if="tab === 'auth'" @maintenance="tab = 'calibration'" />
            <UsersManagement v-else-if="tab === 'users'" />
        </KeepAlive>
        <StereoCalibration v-if="tab === 'calibration'" />
        <ChallengeVerification v-if="tab === 'challenge'" />
        <AccessHistory v-if="tab === 'journal'" />
        </template>
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
        return { tab: 'auth', authorized: false };
    },
    methods: {
        async logout() {
            const response = await fetch('/api/admin/logout', { method: 'POST' });
            if (response.ok || response.status === 401) this.authorized = false;
        }
    }
};
</script>

<style scoped>
.tab-content {
    display: flex;
    gap: 8px;
    align-items: center;
    font-weight: 600;
    color: #361904;
}
</style>
