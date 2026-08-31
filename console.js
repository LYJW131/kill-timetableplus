(() => {
  // --- 只改这一处：开抢时间 ---
  const targetTimeStr = '2026-09-01 08:00:00';
  // --- 配置结束 ---

  const RealDate = window.Date;
  const targetMs = RealDate.parse(targetTimeStr.replace(/-/g, '/'));
  const spoofTargetMs = targetMs + 1000;

  function ConditionalFakeDate(...args) {
    if (RealDate.now() >= targetMs) {
      window.Date = RealDate;
      console.log('[时间已恢复] 模拟已结束，现在返回真实时间。');
      return new RealDate(...args);
    }

    if (this instanceof ConditionalFakeDate) {
      if (args.length === 0) {
        return new RealDate(spoofTargetMs);
      }
      return new RealDate(...args);
    }
    return new RealDate(spoofTargetMs).toString();
  }

  ConditionalFakeDate.prototype = RealDate.prototype;
  ConditionalFakeDate.name = 'Date';
  ConditionalFakeDate.parse = RealDate.parse.bind(RealDate);
  ConditionalFakeDate.UTC = RealDate.UTC.bind(RealDate);

  ConditionalFakeDate.now = () => {
    if (RealDate.now() >= targetMs) {
      window.Date = RealDate;
      console.log('[时间已恢复] 模拟已结束，现在返回真实时间。');
      return RealDate.now();
    }
    return spoofTargetMs;
  };

  window.Date = ConditionalFakeDate;

  console.log(
    `[时间模拟已启动] 网页时间锁定为开抢后 1 秒: ${new Date(spoofTargetMs).toString()}`,
    `\n真实时间到达 ${targetTimeStr} 后将自动恢复。`
  );
})();
