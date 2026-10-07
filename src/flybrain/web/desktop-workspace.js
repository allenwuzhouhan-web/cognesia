/** Native menu commands use the same controls and state checks as the workspace. */
export function initializeDesktopWorkspace({actions,executionButtons,isReady,onStatus,getChecked=()=>({})}) {
  const available=()=>Object.fromEntries(Object.keys(actions).map(key=>[key,key==='stop-all'||(isReady()&&(!executionButtons[key]||!executionButtons[key].disabled))]));
  let last='',queued=false;
  function publish(){queued=false;const detail={ready:isReady(),enabled:available(),checked:getChecked()};const encoded=JSON.stringify(detail);if(encoded!==last){last=encoded;window.dispatchEvent(new CustomEvent('cognesia-desktop-state',{detail}));}}
  function schedule(){if(!queued){queued=true;requestAnimationFrame(publish);}}
  const observer=new MutationObserver(schedule);const controls=document.querySelector('#session-controls');if(controls)observer.observe(controls,{subtree:true,attributes:true,attributeFilter:['disabled'],childList:true,characterData:true});
  const command=event=>{const action=event.detail?.action;if(!Object.hasOwn(actions,action))return;event.preventDefault();if(!available()[action]){onStatus('That command is unavailable in the current simulation state.');return;}Promise.resolve().then(()=>actions[action]()).catch(error=>onStatus(error.message));};
  window.addEventListener('cognesia-desktop-command',command);
  const keydown=event=>{if(!(event.metaKey||event.ctrlKey)||event.altKey)return;const key=event.key.toLowerCase(),action=key==='n'?(event.shiftKey?'toggle-notes':'new-note'):key==='s'&&!event.shiftKey?'save-session':null;if(!action||!Object.hasOwn(actions,action))return;event.preventDefault();command({detail:{action},preventDefault(){}});};
  document.addEventListener('keydown',keydown);
  publish();
  return{refresh:publish,dispose(){observer.disconnect();window.removeEventListener('cognesia-desktop-command',command);document.removeEventListener('keydown',keydown);}};
}
