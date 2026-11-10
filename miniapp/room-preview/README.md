# Mini App 牌桌本地试玩

在仓库根目录启动两个本地进程，然后打开浏览器。炸金花服务仅在本地监听，使用进程内试玩状态。

```sh
.venv/bin/python -m uvicorn vendor.golden_flower.preview:app --host 127.0.0.1 --port 8091
```

```sh
npm --prefix miniapp ci
npm --prefix miniapp run dev
```

打开 [本地牌桌试玩](http://127.0.0.1:5173/miniapp/room-preview.html)。四川血战为一名玩家和三名电脑玩家。炸金花为三名玩家在一台设备上轮流操作。

## 来源与改动

- 四川血战使用 DeskPark 的四川规则引擎、牌桌、麻将牌组件和样式。适配为当前预览的座位和控制器，保留本地推荐，移除上游账户和模型导师接线。[源码版本](https://github.com/solitern/DeskPark/tree/bf232449594da424b86a7adc65f81a8b8de34827) · [许可证](deskpark/LICENSE)
- 炸金花使用 Golden Flower 的服务端规则、扑克牌组件、发牌动画和牌桌背景。服务端包名改为仓库内的 vendor 命名空间，动画接收试玩状态。试玩配置底注 1、当前注额上限 10、轮数上限 20，保留上游比牌和结算行为。[源码版本](https://github.com/luyao618/golden-flower/tree/08817106201990c788b39b4ff64ab84245d96761) · [许可证](golden-flower/LICENSE)

## 规则与接入状态

四川血战沿用 DeskPark 的成都版本。平胡 1 番，对对胡 2 番，清一色、暗七对、全幺九 3 番，清对、将对、清七对、龙七对、清幺九 4 番。根、杠上花、杠上炮、抢杠、海底各加 1 番，天胡、地胡加 4 番。按底分乘以 2 的「番数减一」次方结算，5 番封顶。暗杠由其他未胡玩家各付 2 倍底分，直杠由点杠者付 2 倍底分，巴杠在及时雨时由其他未胡玩家各付 1 倍底分。牌墙摸完时查花猪、查大叫并向应退还者退回杠分，详见 [规则引擎](deskpark/engine/games/sichuan/index.ts)。

本地试玩保留上游金花引擎的原始规则。正式 Mini App 从群内 /rooms 按钮进入，使用独立的服务端房间和群积分结算，按房间 PRD 处理 235、加注档位和多人平局分池。试玩页由 Vite 开发服务器提供。
