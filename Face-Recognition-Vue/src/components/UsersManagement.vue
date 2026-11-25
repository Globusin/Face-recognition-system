<template>
    <div class="d-flex justify-center w-100 h-100">
        <div
            class="d-flex flex-column ga-4 border-md rounded pa-4"
            style="width: 100%"
        >
            <div class="w-100 d-flex justify-space-between align-center flex-wrap ga-2">
                <span class="text-h5">Пользователи</span>

                <v-btn @click="() => (dialogVisible = true)" variant="elevated" color="primary"> Добавить </v-btn>
            </div>

            <v-divider  />
            <v-alert v-if="status" variant="tonal" role="status">{{ status }}</v-alert>

            <v-data-table :headers="headers" :items="users" :items-per-page="10" class="custom-table">
                <template v-slot:item.actions="{ item }">
                    <v-btn color="error" variant="text" size="small" @click="deleteUser(item.id)" class="delete-btn"> Удалить </v-btn>
                </template>
            </v-data-table>
        </div>
        <v-dialog v-model="dialogVisible" max-width="500">
            <v-card>
                <v-card-title class="text-h5" > Регистрация нового пользователя </v-card-title>

                <v-card-text>
                    <p class="mb-4">Для добавления нового пользователя необходимо встать перед камерой.</p>

                    <v-text-field
                        v-model="newUserName"
                        label="Введите имя пользователя"
                        placeholder="Иван Иванов"
                        variant="outlined"
                        color="primary"
                        @keyup.enter="addUser"
                    ></v-text-field>
                </v-card-text>

                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn color="grey-darken-1" variant="text" @click="() => (dialogVisible = false)"> Отмена </v-btn>
                    <v-btn color="primary" variant="elevated" @click="addUser"> Зарегистрировать </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
    </div>
</template>

<script>
export default {
    name: 'UsersManagement',
    data() {
        return {
            status: '',

            headers: [
                { title: 'ID', key: 'id' },
                { title: 'Имя', key: 'name' },
                { title: 'Дата регистрации', key: 'date_registered' },
                { title: 'Действия', key: 'actions', sortable: false },
            ],

            users: [],

            newUserName: '',

            dialogVisible: false,
        };
    },
    activated() {
        this.loadUsers();
    },
    methods: {
        async loadUsers() {
            try {
                const response = await fetch('/api/get_users');
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const data = await response.json();
                this.users = data;
            } catch (error) {
                console.error('Ошибка загрузки пользователей:', error);
                this.status = 'Ошибка загрузки пользователей';
            }
        },

        async addUser() {
            this.status = 'Добавление нового пользователя...';

            try {
                const response = await fetch(`/api/add_user?name=${encodeURIComponent(this.newUserName)}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                });

                const data = await response.json();

                if (data.status === 'success') {
                    this.status = data.message;
                    // Обновляем список пользователей
                    this.loadUsers();
                } else {
                    this.status = data.message || 'Не удалось добавить пользователя';
                }
            } catch (error) {
                this.status = 'Ошибка соединения';
            } finally {
                this.dialogVisible = false;
            }
        },

        async deleteUser(userId) {
            if (confirm('Вы уверены, что хотите удалить этого пользователя?')) {
                try {
                    const response = await fetch(`/api/delete_user/${userId}`, { method: 'DELETE' });
                    const data = await response.json();

                    if (data.status === 'success') {
                        // Обновляем список пользователей
                        this.users = this.users.filter((user) => user.id !== userId);
                    } else {
                        alert(data.message || 'Не удалось удалить пользователя');
                    }
                } catch (error) {
                    alert('Ошибка соединения');
                }
            }
        },
    },
};
</script>

<style scoped>
.custom-table { border: 1px solid #dce1e5; }
.custom-table :deep(th) { background: #f3f5f7; font-weight: 600; }
.custom-table :deep(td) { border-bottom: 1px solid #e2e6ea; }
.delete-btn { text-transform: none; }
</style>
