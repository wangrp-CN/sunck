import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import router from "./router";
import "./style.css";

import { setRouterInstance } from "@/utils/request";

const app = createApp(App);

app.use(createPinia());
app.use(router);
setRouterInstance(router);

// 图标改为按需引入（unplugin-vue-components 的 ElementPlusIconsResolver 自动解析模板中的 <Icon/>）

// 等待路由就绪后再挂载，避免首屏/初始导航时序问题导致页面需手动刷新
router.isReady().then(() => {
  app.mount("#app");
});
