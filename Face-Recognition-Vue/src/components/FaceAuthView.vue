<template>
  <div style="display: flex; flex-direction: column; gap: 3vh;">
    <!-- TABS -->
    <v-tabs
      v-model="tab"
      color="#00d492"
      slider-color="#00d492"
      inset
    >
      <v-tab value="auth">
        <div style="display: flex; gap: 4px; align-items: center;">
          <v-icon icon="mdi-face-recognition"></v-icon>
          <span>Аутентификация</span>
        </div>
      </v-tab>
      <v-tab value="users">
        <div style="display: flex; gap: 4px; align-items: center;">
          <v-icon icon="mdi-account-group"></v-icon>
          <span>Пользователи</span>
        </div>
      </v-tab>
    </v-tabs>

    <!-- AUTH -->
    <div v-if="tab == 'auth'" style="display: flex; gap: 4px">
      <v-sheet :elevation="6" rounded style="padding: 24px; height: 100%; width: 100%; display: flex; flex-direction: column; gap: 10px; border: solid #4a5a8bff;">
          <div style="display: flex; gap: 4px; align-items: center;">
            <v-icon icon="mdi-face-recognition"></v-icon>
            <span style="font-size: 28px;">Распознавание лица</span>
          </div>

          <span>Нажмите кнопку для аутентификации через распознавание лица</span>

          <v-btn text="Аутентификация" @click="authenticateUser" color="#00d492" style="height: 40px;"></v-btn>
      </v-sheet>

      <v-sheet :elevation="6" rounded style="padding: 24px; height: 100%; width: 100%; border: solid #4a5a8bff;">
        <div style="display: flex; flex-direction: column;">
          <span>Статус</span>
          <span>{{ status }}</span>
        </div>
      </v-sheet>
    </div>

    <!-- USERS -->
    <div v-if="tab == 'users'" style="display: flex; gap: 4px">
      <v-sheet :elevation="6" rounded style="padding: 24px; height: 100%; width: 30%; display: flex; flex-direction: column; gap: 10px; border: solid #4a5a8bff;">
        <div style="display: flex; gap: 4px; align-items: center;">
          <v-icon icon="mdi-account-plus"></v-icon>
          <span>Добавить пользователя</span>
        </div>

        <span>Зарегистрировать новое лицо в системе</span>

        <v-text-field label="Введите имя" variant="outlined" v-model="newUserName"></v-text-field>

        <v-btn text="Добавить" @click="addUser(newUserName)" color="#00d492">
          <template #prepend>
            <v-icon icon="mdi-account-plus"></v-icon>
          </template>
        </v-btn>
      </v-sheet>

      <v-sheet :elevation="6" rounded style="padding: 24px; height: 100%; width: 100%; display: flex; flex-direction: column; gap: 10px; border: solid #4a5a8bff;">
        <span>Зарегистрированные пользователи</span>

        <v-data-table
          :headers="headers"
          :items="users"
          :items-per-page="10"
          class="elevation-1"
          style="border-radius: 8px;"
        >
          <template v-slot:item.actions="{ item }">
            <v-btn
              color="error"
              size="small"
              @click="deleteUser(item.id)"
            >
              Удалить
            </v-btn>
          </template>
        </v-data-table>
      </v-sheet>
    </div>
  </div>
</template>

<script>
export default {
  name: 'FaceAuthView',
  data() {
    return {
      tab: 'users',
      status: '',
      headers: [
        { title: 'ID', key: 'id' },
        { title: 'Имя', key: 'name' },
        { title: 'Дата регистрации', key: 'date_registered' },
        { title: 'Действия', key: 'actions', sortable: false }
      ],
      users: [],
      newUserName: ''
    };
  },
  async mounted() {
    await this.loadUsers();
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
    
    async authenticateUser() {
      this.status = 'Выполняется аутентификация...';
      
      try {
        const response = await fetch('/api/authenticate', { method: 'POST' });
        const data = await response.json();
        
        if (data.status === 'success') {
          this.status = 'Аутентификация успешна! Предоставляется доступ.';
        } else {
          this.status = data.message || 'Аутентификация не удалась';
        }
      } catch (error) {
        this.status = 'Ошибка соединения';
      }
    },
    
    async addUser(name) {
      this.status = 'Добавление нового пользователя...';

      try {
        const response = await fetch(`/api/add_user?name=${encodeURIComponent(name)}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          }
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
      }
    },

    
    async deleteUser(userId) {
      if (confirm('Вы уверены, что хотите удалить этого пользователя?')) {
        try {
          const response = await fetch(`/api/delete_user/${userId}`, { method: 'DELETE' });
          const data = await response.json();
          
          if (data.status === 'success') {
            // Обновляем список пользователей
            this.users = this.users.filter(user => user.id !== userId);
          } else {
            alert(data.message || 'Не удалось удалить пользователя');
          }
        } catch (error) {
          alert('Ошибка соединения');
        }
      }
    }
  }
};
</script>

<style scoped>
.v-data-table {
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
  border: 1px solid #e0e0e0;
}

.v-data-table-header th {
  background-color: #f5f5f5;
  font-weight: bold;
 color: #333;
}

.v-data-table-body tr:nth-child(even) {
  background-color: #fafafa;
}

.v-data-table-body tr:hover {
  background-color: #f0f0f0;
}

.v-btn {
  text-transform: none;
}

.v-tab {
  font-weight: 500;
}

.v-sheet {
  padding: 16px;
}
</style>
