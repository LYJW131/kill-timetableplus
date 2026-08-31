(() => {
  // --- 在这里配置 ---
  // 1. 在恢复正常之前，您希望网页显示的时间
  const spoofTargetStr = '2026-09-01 08:00:01';

  // 2. 真实时间到达该时间点后，恢复为真实时间
  const restoreTargetStr = '2026-09-01 08:00:01';
  // --- 配置结束 ---

  // 保存原始的 Date 对象
  const RealDate = window.Date;

  // 计算出目标时间和恢复时间的固定毫秒数
  const spoofTargetMs = RealDate.parse(spoofTargetStr.replace(/-/g, '/'));
  const restoreTargetMs = RealDate.parse(restoreTargetStr.replace(/-/g, '/'));

  // 创建一个带条件的伪造 Date 函数
  function ConditionalFakeDate(...args) {
    // 关键检查：每次调用时都检查一下真实时间
    if (RealDate.now() >= restoreTargetMs) {
      // 如果真实时间已经超过了恢复点，就把原始 Date 对象还回去
      window.Date = RealDate;
      console.log('[时间已恢复] 模拟已结束，现在返回真实时间。');
      // 并且本次调用也返回真实时间
      return new RealDate(...args);
    }

    // --- 如果没到恢复时间，则执行之前的逻辑 ---
    if (this instanceof ConditionalFakeDate) {
      if (args.length === 0) {
        // 返回固定的模拟时间
        return new RealDate(spoofTargetMs);
      }
      return new RealDate(...args);
    }
    return new RealDate(spoofTargetMs).toString();
  }

  // 继承原型和部分静态方法
  ConditionalFakeDate.prototype = RealDate.prototype;
  ConditionalFakeDate.name = 'Date';
  ConditionalFakeDate.parse = RealDate.parse.bind(RealDate);
  ConditionalFakeDate.UTC = RealDate.UTC.bind(RealDate);

  // 同样为静态方法 Date.now() 加上条件判断
  ConditionalFakeDate.now = () => {
    if (RealDate.now() >= restoreTargetMs) {
      // 如果真实时间已经超过了恢复点，就把原始 Date 对象还回去
      window.Date = RealDate;
      console.log('[时间已恢复] 模拟已结束，现在返回真实时间。');
      // 并且本次调用也返回真实时间
      return RealDate.now();
    }
    // 否则，返回固定的模拟时间
    return spoofTargetMs;
  };

  // 用我们的条件性伪造 Date 替换全局 Date
  window.Date = ConditionalFakeDate;

  // 打印初始成功信息
  console.log(
    `[条件性时间模拟已启动] 网页时间将锁定为: ${new Date(spoofTargetMs).toString()}`,
    `\n真实时间到达 ${new Date(restoreTargetMs).toString()} 后将自动恢复。`
  );
})();