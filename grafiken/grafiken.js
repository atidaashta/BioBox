const BIOBOX_CHARTS = {"version": 1, "charts": [{"id": "wachstum", "label": "Wachstum", "file": "01_wachstum.png"}, {"id": "wachstumsrate", "label": "Wachstumsrate", "file": "02_wachstumsrate.png"}, {"id": "farbverlauf", "label": "Farbverlauf", "file": "03_farbverlauf.png"}, {"id": "gesundheit", "label": "Gesundheit", "file": "04_gesundheit.png"}, {"id": "teilscores", "label": "Teilbewertungen", "file": "05_teilscores.png"}]};

'use strict';
(() => {
 const app=document.getElementById('app'),charts=BIOBOX_CHARTS.charts;
 function el(tag,attrs={},...children){
  const node=document.createElement(tag);
  for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);
  node.append(...children);return node;
 }
 const view=el('figure',{'aria-label':'Aktuelle Grafik'});
 app.append(el('header',{},el('h1',{},'BioBox')));
 if(!charts.length){
  view.append(el('p',{class:'empty'},'Keine Grafiken verfügbar.'));
  app.append(view);return;
 }
 const nav=el('nav',{'aria-label':'Grafiken'});
 const open=el('a',{class:'open',target:'_blank',rel:'noopener'},'PNG öffnen');
 const tabs=charts.map(chart=>el('a',{href:'#'+chart.id},chart.label));
 nav.append(...tabs);
 app.append(el('div',{class:'toolbar'},nav,open),view);
 function anzeigen(){
  const index=charts.findIndex(chart=>window.location.hash==='#'+chart.id);
  const i=index<0?0:index, chart=charts[i];
  tabs.forEach((tab,j)=>j===i?tab.setAttribute('aria-current','true'):tab.removeAttribute('aria-current'));
  open.hidden=false;open.setAttribute('href',chart.file);open.setAttribute('aria-label',chart.label+' als PNG öffnen');
  const bild=el('img',{src:chart.file,alt:chart.label});
  bild.addEventListener('error',()=>{
   if(view.firstElementChild!==bild)return;
   open.hidden=true;
   view.replaceChildren(el('p',{class:'empty'},'Grafik nicht verfügbar.'));
  });
  view.replaceChildren(bild);
 }
 window.addEventListener('hashchange',anzeigen);
 anzeigen();
})();
