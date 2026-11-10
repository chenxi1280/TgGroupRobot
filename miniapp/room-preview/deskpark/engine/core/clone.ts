/** 深拷贝纯数据状态。游戏状态约定为可 JSON 序列化，因此这是最可移植的实现（Web / Node / React Native 均可用）。 */
export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}
