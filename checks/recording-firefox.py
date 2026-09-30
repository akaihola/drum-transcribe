import json
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait

options = Options()
options.binary_location = "/etc/profiles/per-user/akaihola/bin/firefox"
options.add_argument("-headless")
options.page_load_strategy = "eager"
options.set_preference("media.navigator.streams.fake", True)
options.set_preference("media.navigator.permission.disabled", True)
options.set_preference("media.autoplay.default", 0)
with webdriver.Firefox(options=options) as driver:
    driver.set_script_timeout(45)
    driver.get("http://localhost:8766/p/dancing-through-life/taustanauha")
    wait = WebDriverWait(driver, 20)
    selector = 'section[data-song="taustanauha"] [data-action="play"]'
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, selector))
    offline_clear = driver.execute_async_script(
        "const finish = arguments[arguments.length-1]; (async()=>{"
        "const r=document.querySelector('section[data-song=taustanauha]').recording;"
        "const old=window.fetch;window.fetch=()=>Promise.reject(Error('Offline test'));"
        "await r.clear();window.fetch=old;return {clearWithoutBacking:true};"
        "})().then(finish,error=>finish({error:error.message}));"
    )
    assert offline_clear.get("clearWithoutBacking") is True, offline_clear
    print(json.dumps(offline_clear), flush=True)
    driver.find_element(By.CSS_SELECTOR, selector).click()
    wait.until(
        lambda d: d.execute_script(
            'return !!document.querySelector("section[data-song=taustanauha]").recording.bus'
        )
    )
    print("Firefox", driver.capabilities["browserVersion"], flush=True)

    def evaluate(script):
        result = driver.execute_async_script(
            "const finish = arguments[arguments.length-1]; Promise.resolve(eval(arguments[0])).then(value=>finish({value}),error=>finish({error:error.message}));",
            script,
        )
        if "error" in result:
            raise RuntimeError(result["error"])
        print(json.dumps(result["value"]), flush=True)
        if isinstance(result["value"], dict):
            failures = [
                name
                for name, value in result["value"].items()
                if value is False and name != "microphoneEcho"
            ]
            if failures:
                raise AssertionError(failures)
        return result["value"]

    evaluate(Path("checks/recording-browser.js").read_text())
    evaluate(Path("checks/recording-backing.js").read_text())
    evaluate(Path("checks/recording-behavior.js").read_text())
    evaluate(Path("checks/recording-mix.js").read_text())
    evaluate(Path("checks/recording-capture.js").read_text())
    evaluate("""(async()=>{
      const r=document.querySelector('section[data-song=taustanauha]').recording;
      const until=async ok=>{while(!ok())await new Promise(res=>setTimeout(res,20));};
      await r.seek(40); await r.setMode('record'); await r.play();
      await until(()=>r.current()>41); await r.pause();
      const result={fakeDeviceCaptured:r.track.segments.length>0,pausedRecordArmed:r.mode==='record'};
      await r.seek(46);result.seekDisarms=r.mode==='playback';await r.setMode('record');
      await r.seek(r.duration-.3);await r.setMode('record');await r.play();
      await until(()=>!r.playing); await r.queue;
      result.songEndStops=!r.playing && r.mode==='playback';
      await r.writes;return result;
    })()""")
    first = driver.current_window_handle
    driver.switch_to.new_window("tab")
    driver.get("http://localhost:8766/p/dancing-through-life/taustanauha")
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, selector))
    driver.find_element(By.CSS_SELECTOR, selector).click()
    wait.until(
        lambda d: d.execute_script(
            'return !!document.querySelector("section[data-song=taustanauha]").recording.bus'
        )
    )
    evaluate(
        '(()=>{const r=document.querySelector("section[data-song=taustanauha]").recording;return {secondTabReadOnly:r.writable===false,restoredSegments:r.track.segments.length}})()'
    )
    driver.close()
    driver.switch_to.window(first)
    evaluate(
        """(async()=>{const r=document.querySelector('section[data-song=taustanauha]').recording;await r.clear();return {cleared:r.track.segments.length===0}})()"""
    )
    evaluate(Path("checks/recording-boundaries.js").read_text())
    driver.refresh()
    wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, selector))
    evaluate(
        "(async()=>{const r=document.querySelector('section[data-song=taustanauha]').recording;const store=await import('/static/recording-store.js');return {clearSurvivesReload:(await store.loadTrack(r.key))===null};})()"
    )
    driver.save_screenshot("/tmp/drum-local-recording-firefox.png")
