const csrfToken=document.querySelector('meta[name="csrf-token"]')?.content;
document.querySelectorAll('form').forEach(form=>{
  if((form.method||'get').toLowerCase()==='post'&&csrfToken&&!form.querySelector('input[name="csrf_token"]')){
    const input=document.createElement('input');input.type='hidden';input.name='csrf_token';input.value=csrfToken;form.prepend(input);
  }
  if(form.dataset.confirm)form.addEventListener('submit',event=>{if(!window.confirm(form.dataset.confirm))event.preventDefault()});
});
document.querySelectorAll('[data-toggle]').forEach(button=>button.addEventListener('click',()=>document.getElementById(button.dataset.toggle)?.classList.toggle('hidden')));
document.querySelectorAll('[data-auto-submit]').forEach(input=>input.addEventListener('change',()=>{if(input.files?.length)input.form?.requestSubmit()}));
document.querySelectorAll('[data-copy-codes]').forEach(button=>button.addEventListener('click',async()=>{
  const codes=[...document.querySelectorAll('.recovery-list code')].map(code=>code.textContent).join('\n');
  try{await navigator.clipboard.writeText(codes);button.textContent='복사했습니다'}catch{button.textContent='복사하지 못했습니다'}
}));
