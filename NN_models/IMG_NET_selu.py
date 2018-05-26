from torch import nn
from torch import optim
import torch.nn.functional as F
import torch
import torch.nn.init as init
from torchvision import datasets, transforms
import time
import os
from NN_models.models import *
import math
def _calculate_lecun_fan(tensor, mode):
    k = tensor.size(0)*tensor.size(1)*tensor.size(2)
    d = tensor.size(3)
    fan_in = k*d
    return fan_in
def lecun_norm_(tensor, a=0, mode='fan_in', nonlinearity='selu'):
    fan = _calculate_lecun_fan(tensor, mode)
    std = 1.0 / math.sqrt(fan)
    with torch.no_grad():
        return tensor.normal_(0, std)
lecun_norm = init._make_deprecate(lecun_norm_)
def train_test(training,file_name):
    distributed = False
    EPOCHES = 200
    ILSVRC2012 = "/data2/ILSVRC2012/"
    traindir = os.path.join(ILSVRC2012, 'train')
    valdir = os.path.join(ILSVRC2012, 'val')
    normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                         std=[0.229, 0.224, 0.225])

    train_dataset = datasets.ImageFolder(
            traindir,
            transforms.Compose([
                transforms.RandomResizedCrop(224),
                transforms.RandomHorizontalFlip(),
                transforms.ToTensor(),
                normalize,
            ]))

    if(distributed):
        # Use a DistributedSampler to restrict each process to a distinct subset of the dataset.
        train_sampler = torch.utils.data.distributed.DistributedSampler(train_dataset)
    else:
        train_sampler = None
    train_loader = torch.utils.data.DataLoader(
        train_dataset, batch_size=256, shuffle=(train_sampler is None),
        num_workers=4, pin_memory=True, sampler=train_sampler)

    val_loader = torch.utils.data.DataLoader(
            datasets.ImageFolder(valdir, transforms.Compose([
                transforms.Resize(256),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                normalize,
            ])),
        batch_size=256, shuffle=False,
        num_workers=4, pin_memory=True)         # default workers = 4
    alexnet = AlexNet(file_name)
    alexnet = alexnet.cuda()
    for weight in alexnet.parameters():
        try:
            lecun_norm(weight, mode='fan_in', nonlinearity='selu')
        except:
            pass
    class AverageMeter(object):
        """Computes and stores the average and current value"""
        def __init__(self):
            self.reset()

        def reset(self):
            self.val = 0
            self.avg = 0
            self.sum = 0
            self.count = 0

        def update(self, val, n=1):
            self.val = val
            self.sum += val * n
            self.count += n
            self.avg = self.sum / self.count
    def accuracy(output, target, topk=(1,)):
        """Computes the precision@k for the specified values of k"""
        maxk = max(topk)
        batch_size = target.size(0)

        _, pred = output.topk(maxk, 1, True, True)
        pred = pred.t().cpu()
        correct = pred.eq(target.view(1, -1).expand_as(pred))

        res = []
        for k in topk:
            correct_k = correct[:k].view(-1).float().sum(0, keepdim=True)
            res.append(correct_k.mul_(100.0 / batch_size))
        return res
    def validate(val_loader, model, criterion):
        batch_time = AverageMeter()
        losses = AverageMeter()
        top1 = AverageMeter()
        top5 = AverageMeter()

        # switch to evaluate mode
        model.eval()

        end = time.time()
        for i, (input, target) in enumerate(val_loader):
            input_var = torch.autograd.Variable(input).cuda()
            target_var = torch.autograd.Variable(target).cuda()

            # compute output
            output = model.forward(input_var)
            loss = criterion(output, target_var)

            # measure accuracy and record loss
            prec1, prec5 = accuracy(output.data, target, topk=(1, 5))
            losses.update(loss.data[0].item(), input.size(0))
            top1.update(prec1[0], input.size(0))
            top5.update(prec5[0], input.size(0))

            # measure elapsed time
            batch_time.update(time.time() - end)
            end = time.time()

        print(' * Prec@1 {top1.avg:.3f} Prec@5 {top5.avg:.3f}'
              .format(top1=top1, top5=top5))
        return ' * Prec@1 {top1.avg:.3f} Prec@5 {top5.avg:.3f}'.format(top1=top1, top5=top5)

    def train(train_loader, model, criterion, optimizer, epoch):
        batch_time = AverageMeter()
        data_time = AverageMeter()
        losses = AverageMeter()
        top1 = AverageMeter()
        top5 = AverageMeter()

        # switch to train mode
        model.train()

        end = time.time()
        for i, (input, target) in enumerate(train_loader):
            # measure data loading time
            data_time.update(time.time() - end)

            input_var = torch.autograd.Variable(input).cuda()
            target_var = torch.autograd.Variable(target).cuda()

            # compute output
            output = model.forward(input_var)
            loss = criterion(output, target_var)

            # measure accuracy and record loss
            prec1, prec5 = accuracy(output.data, target, topk=(1, 5))
            losses.update(loss.data[0].item(), input.size(0))
            top1.update(prec1[0], input.size(0))
            top5.update(prec5[0], input.size(0))

            # compute gradient and do SGD step
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            # measure elapsed time
            batch_time.update(time.time() - end)
            end = time.time()

            print('Epoch: [{0}][{1}/{2}]\t'
                      'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                      'Data {data_time.val:.3f} ({data_time.avg:.3f})\t'
                      'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                      'Prec@1 {top1.val:.3f} ({top1.avg:.3f})\t'
                      'Prec@5 {top5.val:.3f} ({top5.avg:.3f})'.format(
                       epoch, i, len(train_loader), batch_time=batch_time,
                       data_time=data_time, loss=losses, top1=top1, top5=top5))
            if (i % 1000 == 0):
                torch.save(alexnet.state_dict(), os.path.join('NN_models','IMGNET_data','IMGNET_selu.pth'))
    optimizer = optim.Adam(alexnet.parameters(), lr=1e-4, betas=(0.9, 0.99))
    criterion = nn.CrossEntropyLoss(size_average=False)
    if(training == True):
        for epoch in range(EPOCHES):
            train(train_loader,alexnet,criterion,optimizer,epoch)
    else:
        alexnet.load_state_dict(torch.load(os.path.join('NN_models','IMGNET_data','IMGNET_selu.pth')))
        acc1 = validate(val_loader,alexnet,criterion)
        with open(os.path.join('NN_models', 'Acc', 'IMGNET_acc_apx.txt'), 'a') as f:
            f.write(file_name + ' ')
            f.write(acc1 + ' \r\n')