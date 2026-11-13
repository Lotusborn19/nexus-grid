// Rebuilds ../index.html from the part files in this folder.   usage:  node build.js
// The app is one page: p1 = styles, p2 = markup, the rest = scripts (p8 holds start() and must load last).
const fs=require('fs'),path=require('path'),here=__dirname;
const rd=f=>fs.readFileSync(path.join(here,f),'utf8');
const P1=rd('p1.html'),P2=rd('p2.html');
let js='';['p3','p4','p5','p6','p7','p9','p10','p11','p12','p13','p14','p15','p8'].forEach(f=>{
  js+='\n/* ===== '+f+' ===== */\n'+rd(f+'.html').replace(/<\/?script>/g,'')+'\n';
});
try{new Function(js)}catch(e){console.error('JS ERROR:',e.message);process.exit(1)}
const head='<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'+
  '<meta name="description" content="NEXUS // GRID — turn your Android phone into a hacker workstation and learn to use it. Free, open source, no ads.">\n'+
  '<link rel="manifest" href="manifest.webmanifest">\n<link rel="icon" href="icons/icon-192.png">\n<link rel="apple-touch-icon" href="icons/icon-192.png">\n'+
  P1.replace(/<meta name="claude:[^>]*>\n?/,'')+'</head>\n<body>\n';
const out=path.join(here,'..','index.html');
fs.writeFileSync(out,head+P2+'\n<script>\n'+js+'\n</script>\n</body>\n</html>\n');
console.log('built',out,fs.statSync(out).size,'bytes — remember to bump VERSION in sw.js');
