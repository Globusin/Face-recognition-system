<template>
    <div class="d-flex flex-column ga-6">
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
            </v-tabs>
        </div>
        <KeepAlive>
            <FaceAuthentication v-if="tab === 'auth'" />
            <UsersManagement v-else-if="tab === 'users'" />
        </KeepAlive>
        <StereoCalibration v-if="tab === 'calibration'" />
    </div>
</template>

<script>
import FaceAuthentication from './FaceAuthentication.vue';
import UsersManagement from './UsersManagement.vue';
import StereoCalibration from './StereoCalibration.vue';

export default {
    name: 'FaceAuthView',
    components: { FaceAuthentication, UsersManagement, StereoCalibration },
    data() {
        return { tab: 'auth' };
    },
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
